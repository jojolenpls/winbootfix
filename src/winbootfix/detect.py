"""Detection step: platform, disks, ESPs, Windows installations, BitLocker, VMD."""

from __future__ import annotations

import json
import logging
import platform as _py_platform

from winbootfix import __version__, exitcodes, paths
from winbootfix.core.run import CommandError
from winbootfix.core.ui import Cancelled, NeedsChoice
from winbootfix.engine import Finding, Severity
from winbootfix.system import bitlocker, disks, hardware, ntfs, platform, winpath
from winbootfix.system.mounts import MountError
from winbootfix.windows.install import WindowsInstall, read_install

log = logging.getLogger(__name__)


class Stop(Exception):
    """Detection cannot continue; carries the exit code."""

    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def bios_hints(t, vendor: str, topic: str) -> str:
    data = json.loads(paths.data_file("bios_hints.json").read_text(encoding="utf-8"))
    entry = data["vendors"].get(vendor) or data["vendors"]["generic"]
    menus = entry.get(topic) or data["vendors"]["generic"].get(topic, "")
    key = entry.get("setup_key", data["vendors"]["generic"]["setup_key"])
    return t(f"bios.{topic}", vendor=entry.get("name", vendor), menus=menus, key=key)


def system_info(ctx) -> None:
    r, t = ctx.report, ctx.t
    info = hardware.dmi()
    ctx.dmi = info
    r.add_system("report.tool", f"winbootfix {__version__}")
    r.add_system("report.machine", " ".join(x for x in (info.get("sys_vendor"), info.get("product_name")) if x) or "?")
    r.add_system("report.board", " ".join(x for x in (info.get("board_vendor"), info.get("board_name")) if x) or "?")
    firmware = " ".join(info.get(k, "") for k in ("bios_vendor", "bios_version", "bios_date"))
    r.add_system("report.firmware", firmware.strip())
    mode = "UEFI" if platform.is_uefi() else "BIOS/Legacy"
    r.add_system("report.boot_mode", mode)
    if platform.is_uefi():
        r.add_system("report.secure_boot", t(f"secureboot.{platform.secure_boot_state()}"))
    r.add_system("report.linux", f"{_py_platform.release()} {platform.host_arch()}"
                 + (" (live)" if platform.is_live_system() else ""))


def scan_disks(ctx) -> None:
    t, ui = ctx.t, ctx.ui
    ctx.disks = disks.scan()
    internal = [d for d in ctx.disks if not d.is_boot_medium and not d.removable and d.tran != "usb"]
    if not internal:
        internal = [d for d in ctx.disks if not d.is_boot_medium and any(p.maybe_windows for p in d.partitions)]
    hidden = hardware.hidden_storage_controllers()
    ctx.hidden_controllers = hidden
    for d in ctx.disks:
        if not d.is_boot_medium:
            ctx.report.add_system("report.disk", f"{d.path}: {d.describe()} [{d.pttype or '?'}]")
    if hidden:
        ctx.report.add_system("report.storage_controller",
                              ", ".join(f"{c.vendor_name} {c.hwid} ({'VMD' if c.is_vmd else 'RAID'}, "
                                        f"driver={c.driver or '-'})" for c in hidden))
    if not internal:
        vendor = hardware.vendor_key(ctx.dmi)
        ui.error(t("error.no_disk"))
        ui.info(bios_hints(t, vendor, "ahci"))
        ctx.report.add_findings([Finding("system.no_disk", "system", Severity.CRITICAL, "finding.system.no_disk",
                                         advice_key="advice.system.no_disk")])
        raise Stop(exitcodes.NO_DISK)


def _hibernated(root) -> bool:
    hib = winpath.resolve(root, "hiberfil.sys")
    if hib is None:
        return False
    try:
        with open(hib, "rb") as fh:
            return ntfs.is_hibernation_header(fh.read(4))
    except OSError:
        return False


def find_installs(ctx) -> None:
    t, ui, args = ctx.t, ctx.ui, ctx.args
    ctx.locked = []
    for disk in ctx.disks:
        if disk.is_boot_medium:
            continue
        for part in disk.partitions:
            if not part.maybe_windows:
                continue
            vol = ntfs.inspect_volume(part.path)
            device, is_bl = part.path, False
            if vol.kind == "bitlocker":
                key = args.bitlocker_key
                clear = None if key else bitlocker.unlock_clearkey(part.path)
                if clear is not None:
                    device, is_bl = str(clear), True
                    ctx.flags["bitlocker_rw"] = False
                    ctx.report.add_findings([Finding("system.bitlocker_suspended", "system", Severity.INFO,
                                                     "finding.system.bitlocker_suspended", {"partition": part.path})])
                    key = "clear"
                if not key:
                    ctx.locked.append(part)
                    continue
                if key == "clear":
                    pass
                elif key == "ask":
                    try:
                        key = ui.ask_secret(t("question.bitlocker_key", partition=part.path))
                    except (Cancelled, NeedsChoice):
                        ctx.locked.append(part)
                        continue
                if key != "clear":
                    try:
                        want_rw = bool(args.apply and args.command in ("all", "health"))
                        device = str(bitlocker.unlock(part.path, key, rw=want_rw))
                        ctx.flags["bitlocker_rw"] = want_rw
                        is_bl = True
                    except bitlocker.BitLockerError as exc:
                        ui.error(t("error.bitlocker_unlock", partition=part.path, error=str(exc)))
                        ctx.locked.append(part)
                        continue
                vol = ntfs.VolumeInfo("ntfs")
            elif vol.kind != "ntfs":
                continue
            try:
                root = ctx.mounts.mount(device, "ntfs", rw=False, label=f"win-{part.name}")
            except (MountError, CommandError) as exc:
                log.warning("cannot mount %s: %s", part.path, exc)
                continue
            inst = read_install(part, root, device)
            if inst is None:
                ctx.mounts.unmount_device(device)
                continue
            inst.bitlocker = is_bl
            inst.dirty = vol.dirty
            inst.hibernated = _hibernated(root)
            ctx.installs.append(inst)
            log.info("found %s on %s", inst.label, part.path)


def choose_install(ctx) -> WindowsInstall:
    t, args = ctx.t, ctx.args
    installs = ctx.installs
    if args.windows:
        for inst in installs:
            if inst.partition.path == args.windows or inst.partition.name == args.windows.split("/")[-1]:
                return inst
        ctx.ui.error(t("error.windows_not_found", partition=args.windows))
        raise Stop(exitcodes.USAGE)
    if len(installs) == 1:
        return installs[0]
    ordered = sorted(installs, key=lambda i: i.last_shutdown.timestamp() if i.last_shutdown else 0, reverse=True)
    options = []
    for inst in ordered:
        when = inst.last_shutdown.strftime("%Y-%m-%d") if inst.last_shutdown else "?"
        disk = inst.partition.disk.describe() if inst.partition.disk else ""
        options.append((inst.partition.path, t("question.windows_option", label=inst.label,
                                                partition=inst.partition.path, disk=disk, date=when)))
    try:
        chosen = ctx.ui.choose(t("question.choose_windows"), options, default=ordered[0].partition.path)
    except NeedsChoice:
        chosen = ordered[0].partition.path
    return next(i for i in installs if i.partition.path == chosen)


def choose_esp(ctx):
    t, args = ctx.t, ctx.args
    esps = disks.find_esps(ctx.disks)
    ctx.esps = esps
    if args.esp:
        for p in esps:
            if p.path == args.esp or p.name == args.esp.split("/")[-1]:
                return p
        ctx.ui.error(t("error.esp_not_found", partition=args.esp))
        raise Stop(exitcodes.USAGE)
    inst = ctx.install
    same_disk = [p for p in esps if inst and p.disk_path == inst.partition.disk_path]
    if len(same_disk) == 1:
        return same_disk[0]
    pool = same_disk or esps
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]
    options = [(p.path, t("question.esp_option", partition=p.path, disk=p.disk.describe() if p.disk else "",
                          size=int(p.size / 1e6))) for p in pool]
    try:
        chosen = ctx.ui.choose(t("question.choose_esp"), options, default=pool[0].path)
    except NeedsChoice:
        chosen = pool[0].path
    return next(p for p in pool if p.path == chosen)


def legacy_check(ctx) -> bool:
    """Return True if the boot module can run (UEFI). Explains the legacy cases otherwise."""
    if platform.is_uefi():
        return True
    windows_on_mbr = any(
        p.maybe_windows and d.pttype == "dos" for d in ctx.disks if not d.is_boot_medium for p in d.partitions
    )
    if windows_on_mbr:
        ctx.report.add_findings([Finding("system.legacy_windows", "system", Severity.CRITICAL,
                                         "finding.system.legacy_windows", advice_key="advice.system.legacy_windows")])
    else:
        ctx.report.add_findings([Finding("system.usb_legacy", "system", Severity.CRITICAL,
                                         "finding.system.usb_legacy", advice_key="advice.system.usb_legacy")])
    return False


def run_detection(ctx) -> None:
    t, ui = ctx.t, ctx.ui
    ui.title(t("step.detect"))
    system_info(ctx)
    scan_disks(ctx)
    ctx.boot_possible = legacy_check(ctx)
    find_installs(ctx)
    if not ctx.installs:
        if ctx.locked:
            ui.error(t("error.bitlocker_locked", partitions=", ".join(p.path for p in ctx.locked)))
            ui.info(t("advice.bitlocker"))
            ctx.report.add_findings([Finding("system.bitlocker", "system", Severity.CRITICAL,
                                             "finding.system.bitlocker", advice_key="advice.bitlocker")])
            raise Stop(exitcodes.BITLOCKER_LOCKED)
        ui.error(t("error.no_windows"))
        if getattr(ctx, "hidden_controllers", None):
            ui.info(bios_hints(t, hardware.vendor_key(ctx.dmi), "ahci"))
        ctx.report.add_findings([Finding("system.no_windows", "system", Severity.CRITICAL,
                                         "finding.system.no_windows", advice_key="advice.system.no_windows")])
        raise Stop(exitcodes.NO_WINDOWS)
    for part in ctx.locked:
        ctx.report.add_findings([Finding("system.bitlocker_other", "system", Severity.INFO,
                                         "finding.system.bitlocker_other", {"partition": part.path})])
    ctx.install = choose_install(ctx)
    inst = ctx.install
    ctx.report.add_system("report.windows", f"{inst.label} [{inst.arch}] - {inst.partition.path}")
    if inst.language:
        ctx.report.add_system("report.windows_language", inst.language)
    if inst.arch == "arm64":
        ui.error(t("error.arm64"))
        ctx.report.add_findings([Finding("system.arm64", "system", Severity.CRITICAL, "finding.system.arm64")])
        raise Stop(exitcodes.UNSUPPORTED_ARCH)
    if inst.hibernated:
        ctx.report.add_findings([Finding("system.hibernated", "system", Severity.WARNING,
                                         "finding.system.hibernated", advice_key="advice.system.hibernated")])
    elif inst.dirty:
        ctx.report.add_findings([Finding("system.dirty", "system", Severity.INFO, "finding.system.dirty",
                                         advice_key="advice.system.dirty")])
    ctx.esp = choose_esp(ctx)
    ui.info(t("detect.summary", windows=inst.label, partition=inst.partition.path,
              esp=ctx.esp.path if ctx.esp else "-"))
