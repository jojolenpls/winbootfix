"""Command line interface."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from winbootfix import __version__, exitcodes
from winbootfix.core import guard, i18n
from winbootfix.core import log as wlog
from winbootfix.core.backup import NoBackupTarget
from winbootfix.core.i18n import Translator
from winbootfix.core.ui import UI, Cancelled, make_ui
from winbootfix.engine import Executor, Plan, Severity

log = logging.getLogger(__name__)

COMMANDS = ("all", "boot", "health", "report", "restore", "list-backups", "menu")
REPORT_DIR = Path("/var/log/winbootfix-reports")


def _prelang(argv: list[str]) -> str | None:
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return None


def _translate_argparse(t: Translator) -> None:
    mapping = {
        "usage: ": t("argparse.usage"),
        "positional arguments": t("argparse.positional"),
        "options": t("argparse.options"),
        "optional arguments": t("argparse.options"),
        "show this help message and exit": t("cli.help"),
        "%(prog)s: error: %(message)s\n": t("argparse.error"),
        "invalid choice: %(value)r (choose from %(choices)s)": t("argparse.invalid_choice"),
        "unrecognized arguments: %s": t("argparse.unrecognized"),
        "expected one argument": t("argparse.expected_one"),
    }
    argparse._ = lambda s: mapping.get(s, s)  # type: ignore[attr-defined]


def build_parser(t: Translator) -> argparse.ArgumentParser:
    _translate_argparse(t)
    p = argparse.ArgumentParser(prog="winbootfix", description=t("cli.description"), epilog=t("cli.epilog"),
                                formatter_class=argparse.RawDescriptionHelpFormatter, add_help=False)
    p.add_argument("-h", "--help", action="help", help=t("cli.help"))
    p.add_argument("--version", action="version", version=f"winbootfix {__version__}", help=t("cli.version"))
    p.add_argument("command", nargs="?", default="all", choices=COMMANDS, metavar="COMMAND",
                   help=t("cli.command"))
    p.add_argument("target", nargs="?", help=t("cli.target"))
    g = p.add_argument_group(t("cli.group_safety"))
    g.add_argument("--dry-run", action="store_true", help=t("cli.dry_run"))
    g.add_argument("--apply", action="store_true", help=t("cli.apply"))
    g.add_argument("-y", "--yes", action="store_true", help=t("cli.yes"))
    g.add_argument("--backup-dir", metavar="DIR", help=t("cli.backup_dir"))
    g.add_argument("--allow-volatile-backup", action="store_true", help=t("cli.allow_volatile_backup"))
    g.add_argument("--allow-hiberfile-removal", action="store_true", help=t("cli.allow_hiberfile_removal"))
    s = p.add_argument_group(t("cli.group_select"))
    s.add_argument("--expert", action="store_true", help=t("cli.expert"))
    s.add_argument("--windows", metavar="PARTITION", help=t("cli.windows"))
    s.add_argument("--esp", metavar="PARTITION", help=t("cli.esp"))
    s.add_argument("--bitlocker-key", metavar="KEY", help=t("cli.bitlocker_key"))
    s.add_argument("--windows-first", action="store_true", help=t("cli.windows_first"))
    o = p.add_argument_group(t("cli.group_output"))
    o.add_argument("--lang", metavar="CODE", help=t("cli.lang", langs=", ".join(t.available())))
    o.add_argument("--report-dir", metavar="DIR", help=t("cli.report_dir"))
    o.add_argument("--log", metavar="FILE", help=t("cli.log"))
    o.add_argument("--json", action="store_true", help=t("cli.json"))
    o.add_argument("--ui", choices=("auto", "console", "whiptail"), default="auto", help=t("cli.ui"))
    o.add_argument("--no-color", action="store_true", help=t("cli.no_color"))
    o.add_argument("-v", "--verbose", action="store_true", help=t("cli.verbose"))
    return p


def show_findings(ui: UI, t: Translator, plan: Plan, expert: bool) -> None:
    ui.title(t("step.results"))
    shown = [f for f in sorted(plan.findings, key=lambda x: -x.severity)
             if expert or f.severity >= Severity.WARNING]
    if not any(f.severity >= Severity.WARNING for f in plan.findings):
        ui.success(t("results.all_good"))
    for f in shown:
        line = f"[{t(f.severity.key)}] {f.title(t)}"
        if f.severity >= Severity.ERROR:
            ui.error(line)
        elif f.severity == Severity.WARNING:
            ui.warn(line)
        else:
            ui.info(line)
        advice = f.advice(t)
        if advice:
            ui.info("    -> " + advice)
        if expert:
            for d in f.details:
                ui.info("       " + d)


def save_report(ctx, extra_dirs: list[Path] | None = None) -> list[Path]:
    dirs = [Path(ctx.args.report_dir)] if ctx.args.report_dir else [REPORT_DIR]
    dirs += extra_dirs or []
    written = []
    for d in dirs:
        try:
            written += ctx.report.save(d)
        except OSError as exc:
            log.warning("cannot write report to %s: %s", d, exc)
    return written


def _filter_blocked(ctx, plan: Plan) -> None:
    """Drop actions that need write access to a Windows volume we must not write to."""
    t, ui, args, inst = ctx.t, ctx.ui, ctx.args, ctx.install
    win_actions = [a for a in plan.actions if "win_rw" in a.needs]
    if not win_actions or inst is None:
        return
    if inst.hibernated and not args.allow_hiberfile_removal:
        allow = False
        if args.apply and ui.interactive and not args.yes:
            try:
                allow = ui.confirm(t("question.remove_hiberfile"), default=False)
            except Cancelled:
                allow = False
        if allow:
            args.allow_hiberfile_removal = True
            return
        plan.actions = [a for a in plan.actions if "win_rw" not in a.needs]
        from winbootfix.engine import Finding
        plan.findings.append(Finding("system.win_rw_blocked", "system", Severity.WARNING,
                                     "finding.system.win_rw_blocked", advice_key="advice.system.hibernated"))
    elif inst.bitlocker and not ctx.flags.get("bitlocker_rw"):
        plan.actions = [a for a in plan.actions if "win_rw" not in a.needs]


def exit_code(plan: Plan, results, applied_mode: bool) -> int:
    problems = bool(plan.problems())
    if not applied_mode or not results:
        return exitcodes.ISSUES_FOUND if problems else exitcodes.OK
    statuses = {r.status for r in results}
    if statuses == {"cancelled"}:
        return exitcodes.CANCELLED
    if statuses <= {"applied"}:
        return exitcodes.REPAIRED
    return exitcodes.PARTIAL


def run_repair(ctx) -> int:
    from winbootfix import detect, health
    from winbootfix.boot import diagnose as boot_diag
    from winbootfix.health.postdeploy import DeployPostScriptAction

    t, ui, args = ctx.t, ctx.ui, ctx.args
    try:
        detect.run_detection(ctx)
    except detect.Stop as stop:
        return stop.code
    if not args.lang and not os.environ.get("WINBOOTFIX_LANG") and ctx.install.language:
        ctx.t.set_language(ctx.install.language)

    plan = Plan()
    if args.command in ("all", "boot") and ctx.boot_possible:
        ui.title(t("step.boot"))
        plan.extend(boot_diag.diagnose(ctx))
    if args.command in ("all", "health"):
        ui.title(t("step.health"))
        plan.extend(health.diagnose(ctx))
    if ctx.flags.get("post_reasons"):
        plan.actions.append(DeployPostScriptAction())
    _filter_blocked(ctx, plan)
    ctx.report.add_findings(plan.findings)
    show_findings(ui, t, Plan(findings=ctx.report.findings), args.expert)

    applied_mode = bool(args.apply)
    if plan.actions and not applied_mode:
        ui.title(t("step.plan"))
        for a in plan.actions:
            ui.info(f"- {a.explain(t)}" + (f" ({t('engine.experimental')})" if a.experimental else ""))
        ui.info("")
        ui.info(t("results.how_to_apply"))
    if plan.actions and applied_mode and any(a.id == "boot.nvram" or a.id == "boot.nvram_order" for a in plan.actions):
        try:
            boot_diag.ask_boot_order(ctx)
        except Cancelled:
            ctx.flags["windows_first"] = False

    try:
        results = Executor(ctx, apply=applied_mode, expert=args.expert).execute(plan)
    except NoBackupTarget as exc:
        ui.error(str(exc))
        ui.info(t("advice.backup_target"))
        save_report(ctx)
        return exitcodes.NO_BACKUP_TARGET
    if applied_mode:
        ctx.report.add_results(results)
        ui.title(t("step.done"))
        for r in results:
            text = f"[{t('status.' + r.status)}] {r.action.explain(t)}"
            (ui.success if r.status == "applied" else ui.warn)(text + (f" - {r.error}" if r.error else ""))
    code = exit_code(plan, results, applied_mode)
    if code == exitcodes.REPAIRED:
        ui.success(t("final.repaired"))
        if any(r.action.id == "health.post_script" and r.status == "applied" for r in results):
            ui.info(t("final.post_script"))
    extra = [ctx.backups.dir] if ctx.backups.dir else []
    written = save_report(ctx, extra)
    if written:
        ui.info(t("final.report_saved", path=str(written[0])))
    return code


def run_restore(ctx) -> int:
    from winbootfix import detect
    from winbootfix.core import restore

    t, ui, args = ctx.t, ctx.ui, ctx.args
    if not args.target:
        ui.error(t("error.restore_needs_dir"))
        return exitcodes.USAGE
    bdir = Path(args.target)
    try:
        manifest = restore.load_manifest(bdir)
    except (OSError, ValueError):
        ui.error(t("error.restore_bad_dir", path=str(bdir)))
        return exitcodes.USAGE
    try:
        detect.run_detection(ctx)
    except detect.Stop as stop:
        return stop.code
    ui.show_text(t("restore.title"), "\n".join(restore.describe(manifest)) or "-")
    if not args.apply:
        ui.info(t("results.how_to_apply"))
        return exitcodes.OK
    if not ui.confirm(t("restore.confirm"), default=False):
        return exitcodes.CANCELLED
    with guard.allow_writes():
        errors = restore.restore_all(ctx, bdir)
    for e in errors:
        ui.error(e)
    if errors:
        return exitcodes.PARTIAL
    ui.success(t("restore.done"))
    return exitcodes.REPAIRED


def list_backups(ctx) -> int:
    t, ui = ctx.t, ctx.ui
    found = []
    for tg in ctx.persistent_targets() + [None]:
        base = (tg.path if tg else Path("/run/winbootfix")) / "winbootfix-backups"
        if base.is_dir():
            found += sorted(p for p in base.iterdir() if (p / "manifest.json").is_file())
    if not found:
        ui.info(t("restore.none"))
    for p in found:
        ui.info(str(p))
    return exitcodes.OK


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    lang = _prelang(argv)
    t = Translator(i18n.detect_language(lang))
    i18n.set_current(t)
    parser = build_parser(t)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exitcodes.OK if exc.code in (0, None) else exitcodes.USAGE
    if args.apply and args.dry_run:
        parser.print_usage(sys.stderr)
        print(t("error.apply_and_dry_run"), file=sys.stderr)
        return exitcodes.USAGE
    if args.command == "report":
        args.apply = False
    logp = wlog.setup(args.log, args.verbose)
    ui = make_ui(t, args.yes, mode=args.ui, color=False if args.no_color else None)

    if args.command == "menu":
        from winbootfix import menu
        return menu.run(args, t)

    from winbootfix.system import platform
    if not platform.is_root():
        ui.error(t("error.not_root"))
        return exitcodes.NOT_ROOT

    from winbootfix.context import Context
    ctx = Context(args, t, ui)
    try:
        if args.command == "restore":
            return run_restore(ctx)
        if args.command == "list-backups":
            return list_backups(ctx)
        code = run_repair(ctx)
        if args.json:
            print(json.dumps(ctx.report.to_dict(), indent=2, ensure_ascii=False))
        return code
    except (KeyboardInterrupt, Cancelled):
        ui.warn(t("error.cancelled"))
        return exitcodes.CANCELLED
    except Exception:  # noqa: BLE001
        log.exception("internal error")
        ui.error(t("error.internal", log=str(logp)))
        try:
            save_report(ctx)
        except Exception:  # noqa: BLE001
            pass
        return exitcodes.INTERNAL
    finally:
        ctx.close()
