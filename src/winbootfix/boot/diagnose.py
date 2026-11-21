"""Module A: diagnose the Windows boot chain and plan the repairs (levels a, b, c)."""

from __future__ import annotations

import logging

from winbootfix.boot import certs, efifiles, nvram, repair
from winbootfix.boot.bcd import validate as bcdvalidate
from winbootfix.core.run import CommandError, which
from winbootfix.engine import Finding, Plan, Severity
from winbootfix.system import platform, winpath

log = logging.getLogger(__name__)

SERIOUS_BCD_PROBLEMS = {"unreadable", "no_bootmgr", "no_default", "default_missing",
                        "default_not_osloader", "device_mismatch", "osdevice_mismatch"}


def _f(plan: Plan, fid: str, sev: Severity, key: str, advice: str | None = None, details=None, **params):
    plan.findings.append(Finding(fid, "boot", sev, key, params, advice, dict(params), details or []))


def diagnose(ctx) -> Plan:
    plan = Plan()
    inst, esp = ctx.install, ctx.esp
    if esp is None:
        _f(plan, "boot.esp_missing", Severity.CRITICAL, "finding.boot.esp_missing", "advice.boot.esp_missing")
        return plan
    if not esp.disk or not esp.disk.is_gpt:
        _f(plan, "boot.esp_not_gpt", Severity.ERROR, "finding.boot.esp_not_gpt", "advice.winpe")
        return plan

    esp_root = ctx.esp_mount()
    st = efifiles.status(esp_root)
    ctx.report.add_system("report.esp", f"{esp.path} ({esp.disk.describe()})")

    # --- EFI files (level b) -------------------------------------------------
    need_copy = st.bootmgr is None or not st.bootmgr_valid
    if st.bootmgr is None:
        _f(plan, "boot.bootmgr_missing", Severity.CRITICAL, "finding.boot.bootmgr_missing",
           "advice.boot.copy_files")
    elif not st.bootmgr_valid:
        _f(plan, "boot.bootmgr_invalid", Severity.CRITICAL, "finding.boot.bootmgr_invalid",
           "advice.boot.copy_files")
    else:
        _f(plan, "boot.bootmgr_ok", Severity.INFO, "finding.boot.bootmgr_ok")

    fw = certs.firmware_certs()
    sb = platform.secure_boot_state()
    existing_signer = certs.binary_signer(st.bootmgr) if st.bootmgr and st.bootmgr_valid else None
    boot_dir = winpath.resolve(inst.windows_dir, "Boot") or inst.windows_dir
    boot_set, reason = certs.choose_boot_set(boot_dir, fw, existing_signer, sb)
    ctx.flags["boot_set"] = boot_set
    if reason == "no_ex_but_2011_revoked":
        _f(plan, "boot.ca2011_revoked", Severity.WARNING, "finding.boot.ca2011_revoked",
           "advice.boot.ca2011_revoked")

    if st.other_loaders:
        _f(plan, "boot.other_os", Severity.INFO, "finding.boot.other_os", None,
           loaders=", ".join(st.other_loaders))

    with_fallback = st.fallback is None
    if st.fallback is not None and not st.fallback_is_microsoft:
        _f(plan, "boot.fallback_foreign", Severity.INFO, "finding.boot.fallback_foreign")

    if need_copy:
        try:
            items = efifiles.copy_plan(inst.windows_dir, boot_set)
        except FileNotFoundError as exc:
            _f(plan, "boot.no_source_files", Severity.CRITICAL, "finding.boot.no_source_files",
               "advice.winpe", [str(exc)])
        else:
            plan.actions.append(repair.CopyEfiFilesAction(items, with_fallback, boot_set,
                                                          esp=esp.path, windows=inst.label))
            with_fallback = False
    elif with_fallback:
        _f(plan, "boot.fallback_missing", Severity.INFO, "finding.boot.fallback_missing")
        plan.actions.append(repair.FallbackAction())

    # --- BCD (level c) -----------------------------------------------------------
    win_uuids = [i.partition.partuuid for i in ctx.installs if i.partition.partuuid]
    need_bcd = False
    if st.bcd is None:
        need_bcd = True
        _f(plan, "boot.bcd_missing", Severity.CRITICAL, "finding.boot.bcd_missing", "advice.boot.bcd")
    else:
        summary = bcdvalidate.read(st.bcd)
        problems = bcdvalidate.check(summary, esp.partuuid, win_uuids)
        serious = sorted(set(problems) & SERIOUS_BCD_PROBLEMS)
        if serious:
            need_bcd = True
            _f(plan, "boot.bcd_invalid", Severity.CRITICAL, "finding.boot.bcd_invalid", "advice.boot.bcd",
               [f"BCD: {', '.join(problems)}"])
        elif problems:
            _f(plan, "boot.bcd_unverifiable", Severity.INFO, "finding.boot.bcd_unverifiable", None,
               [f"BCD: {', '.join(problems)}"])
        else:
            _f(plan, "boot.bcd_ok", Severity.INFO, "finding.boot.bcd_ok")
    if need_bcd:
        template = inst.config("BCD-Template")
        if template is None or not inst.partition.partuuid or not esp.disk.ptuuid or not inst.partition.disk \
                or not inst.partition.disk.ptuuid or not esp.partuuid:
            _f(plan, "boot.bcd_cannot_build", Severity.ERROR, "finding.boot.bcd_cannot_build", "advice.winpe")
        else:
            plan.actions.append(repair.BuildBcdAction(
                template=template,
                esp_ids=(esp.partuuid, esp.disk.ptuuid),
                win_ids=(inst.partition.partuuid, inst.partition.disk.ptuuid),
                locale=inst.language or "en-US",
                os_description="Windows 11" if inst.is_win11 else "Windows 10",
                windows_partuuids=win_uuids,
                windows=inst.label,
            ))
            ctx.flags.setdefault("post_reasons", set()).add("bcd")

    # --- NVRAM entry (level a) -------------------------------------------------------
    if not platform.is_uefi():
        return plan
    if not which("efibootmgr"):
        _f(plan, "boot.no_efibootmgr", Severity.ERROR, "finding.boot.no_efibootmgr", "advice.install_efibootmgr")
        return plan
    try:
        state = nvram.read_state()
    except CommandError as exc:
        _f(plan, "boot.nvram_unreadable", Severity.ERROR, "finding.boot.nvram_unreadable",
           "advice.boot.nvram_unreadable", [str(exc)])
        return plan
    ctx.boot_state = state

    entries = state.windows_entries()
    good = [e for e in entries if e.points_to(esp.partuuid) and e.is_windows]
    stale = [e for e in entries if e not in good]
    for e in stale:
        _f(plan, "boot.nvram_stale", Severity.WARNING, "finding.boot.nvram_stale", None,
           [e.devpath], num=e.num)

    first_other = nvram.other_os_first(state)
    if first_other is not None:
        ctx.flags.setdefault("other_os_first", first_other.label)

    deps = tuple(a.id for a in plan.actions if a.id == "boot.copy_files")
    if not good:
        _f(plan, "boot.nvram_missing", Severity.CRITICAL, "finding.boot.nvram_missing", "advice.boot.nvram")
        action = repair.CreateEntryAction(esp.disk.path, esp.number or 1, esp.partuuid or "",
                                          disk=esp.disk.describe(), partition=esp.number)
        action.depends_on = deps
        plan.actions.append(action)
    else:
        entry = good[0]
        if not entry.active or entry.num not in state.order:
            _f(plan, "boot.nvram_inactive", Severity.ERROR, "finding.boot.nvram_inactive", None, num=entry.num)
            action = repair.FixEntryOrderAction(entry.num, activate=not entry.active, num=entry.num)
            action.depends_on = deps
            plan.actions.append(action)
        else:
            _f(plan, "boot.nvram_ok", Severity.INFO, "finding.boot.nvram_ok", num=entry.num)
    return plan


def ask_boot_order(ctx) -> None:
    """Before confirmation: decide whether Windows goes before another OS loader (GRUB...)."""
    if ctx.args.windows_first:
        ctx.flags["windows_first"] = True
        return
    other = ctx.flags.get("other_os_first")
    if not other:
        ctx.flags["windows_first"] = True
        return
    choice = ctx.ui.choose(ctx.t("question.boot_order", other=other),
                           [("keep", ctx.t("question.boot_order_keep", other=other)),
                            ("windows", ctx.t("question.boot_order_windows"))], default="keep")
    ctx.flags["windows_first"] = choice == "windows"
