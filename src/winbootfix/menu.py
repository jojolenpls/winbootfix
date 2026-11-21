"""Menu shown automatically when the bootable ISO starts (whiptail)."""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from winbootfix import exitcodes, paths
from winbootfix.core.i18n import Translator
from winbootfix.core.ui import Cancelled, WhiptailUI, make_ui

log = logging.getLogger(__name__)

READY_MARKER = "WINBOOTFIX-MENU-READY"


def _kmsg(text: str) -> None:
    try:
        with open("/dev/kmsg", "w") as fh:
            fh.write(f"winbootfix: {text}\n")
    except OSError:
        pass


def detect_windows_language() -> tuple[str | None, str | None]:
    """Quick read-only probe: (language tag, keyboard layout id) of the first Windows found."""
    from winbootfix.system import disks, ntfs
    from winbootfix.system.mounts import MountManager
    from winbootfix.windows.install import read_install

    mm = MountManager()
    try:
        for disk in disks.scan():
            if disk.is_boot_medium:
                continue
            for part in disk.partitions:
                if not part.maybe_windows or ntfs.inspect_volume(part.path).kind != "ntfs":
                    continue
                try:
                    root = mm.mount(part.path, "ntfs", label=f"probe-{part.name}")
                except Exception:  # noqa: BLE001
                    continue
                inst = read_install(part, root, part.path)
                if inst and inst.language:
                    return inst.language, inst.keyboard_lcid
    except Exception:  # noqa: BLE001
        log.exception("language probe failed")
    finally:
        mm.cleanup()
    return None, None


def keymap_for(lang: str | None, keyboard_lcid: str | None = None) -> str | None:
    try:
        table = json.loads(paths.data_file("languages.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if keyboard_lcid:
        km = table.get("keyboard", {}).get(keyboard_lcid.lower()[-4:])
        if km:
            return km
    if lang:
        return table.get("keymap", {}).get(lang) or table.get("keymap", {}).get(lang.split("-")[0])
    return None


def set_keymap(lang: str | None, keyboard_lcid: str | None = None) -> None:
    """Switch the console keyboard (AZERTY for French Windows, etc.) with console-setup."""
    km = keymap_for(lang, keyboard_lcid)
    if not km:
        return
    layout, _, variant = km.partition(":")
    try:
        Path("/etc/default/keyboard").write_text(
            f'XKBMODEL="pc105"\nXKBLAYOUT="{layout}"\nXKBVARIANT="{variant}"\nXKBOPTIONS=""\nBACKSPACE="guess"\n',
            encoding="utf-8")
    except OSError:
        return
    subprocess.run(["setupcon", "-k", "--force"], capture_output=True, check=False)


def tool_command() -> list[str]:
    """The installed launcher, or the package run by the current interpreter (development checkout)."""
    import shutil
    launcher = shutil.which("winbootfix")
    if launcher:
        return [launcher]
    code = f"import sys; sys.path.insert(0, {str(paths.PACKAGE_DIR.parent)!r}); from winbootfix.cli import main; " \
        "sys.exit(main())"
    return [sys.executable, "-c", code]


def run_tool(extra: list[str], t: Translator) -> int:
    cmd = tool_command() + ["--lang", t.lang] + extra
    os.system("clear")
    code = subprocess.call(cmd)
    input("\n" + t("menu.press_enter"))
    return code


def export_report(t: Translator, ui) -> None:
    from winbootfix.system import disks, media
    from winbootfix.system.mounts import MountManager

    reports = sorted(Path("/var/log/winbootfix-reports").glob("winbootfix-*"))
    if not reports:
        ui.show_text(t("menu.export"), t("menu.no_report"))
        return
    mounts = MountManager()
    from winbootfix.core import guard
    with guard.allow_writes():
        targets = [tg for tg in media.candidate_targets(disks.scan(), mounts) if tg.kind != "local"]
    if not targets:
        ui.show_text(t("menu.export"), t("menu.no_target"))
        return
    key = ui.choose(t("menu.export_where"), [(str(i), t(f"target.{tg.kind}", label=tg.label))
                                            for i, tg in enumerate(targets)], default="0")
    dest = targets[int(key)].path / "winbootfix-reports"
    dest.mkdir(parents=True, exist_ok=True)
    import shutil
    for r in reports:
        shutil.copy2(r, dest / r.name)
    logf = Path("/var/log/winbootfix.log")
    if logf.exists():
        shutil.copy2(logf, dest / "winbootfix.log")
    subprocess.run(["sync"], check=False)
    mounts.cleanup()
    ui.show_text(t("menu.export"), t("menu.exported", path=str(dest)))


def run(args: argparse.Namespace, t: Translator) -> int:
    ui = make_ui(t, False, mode="whiptail")
    _kmsg(READY_MARKER)
    if not args.lang:
        lang, kb = detect_windows_language()
        if lang:
            t.set_language(lang)
            set_keymap(lang, kb)
    while True:
        try:
            choice = ui.choose(t("menu.title"), [
                ("repair", t("menu.repair")),
                ("diagnose", t("menu.diagnose")),
                ("expert", t("menu.expert")),
                ("export", t("menu.export")),
                ("language", t("menu.language")),
                ("shell", t("menu.shell")),
                ("reboot", t("menu.reboot")),
                ("poweroff", t("menu.poweroff")),
            ], default="repair")
        except Cancelled:
            continue
        if choice == "repair":
            run_tool(["--apply"], t)
        elif choice == "diagnose":
            run_tool([], t)
        elif choice == "expert":
            try:
                sub = ui.choose(t("menu.expert"), [
                    ("all", t("menu.expert_all")), ("boot", t("menu.expert_boot")),
                    ("health", t("menu.expert_health")), ("bitlocker", t("menu.expert_bitlocker")),
                    ("restore", t("menu.expert_restore")),
                ], default="all")
            except Cancelled:
                continue
            if sub == "bitlocker":
                run_tool(["--expert", "--apply", "--bitlocker-key", "ask"], t)
            elif sub == "restore":
                run_tool(["list-backups"], t)
            else:
                run_tool([sub, "--expert", "--apply"], t)
        elif choice == "export":
            try:
                export_report(t, ui)
            except Cancelled:
                pass
        elif choice == "language":
            try:
                code = ui.choose(t("menu.language"), list(t.available().items()), default=t.lang)
            except Cancelled:
                continue
            t.set_language(code)
            set_keymap(code)
        elif choice == "shell":
            os.system("clear")
            print(t("menu.shell_hint"))
            subprocess.call(["/bin/bash", "-l"])
        elif choice == "reboot":
            if ui.confirm(t("menu.confirm_reboot")):
                subprocess.call(["systemctl", "reboot"])
                return exitcodes.OK
        elif choice == "poweroff":
            if ui.confirm(t("menu.confirm_poweroff")):
                subprocess.call(["systemctl", "poweroff"])
                return exitcodes.OK
        if not isinstance(ui, WhiptailUI) and not sys.stdin.isatty():
            return exitcodes.OK
