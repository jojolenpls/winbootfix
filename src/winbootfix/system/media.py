"""Persistent places to store backups and reports.

On the live ISO everything in RAM is lost at reboot, so backups must go to
a real disk: the boot USB stick when it is writable (Rufus FAT32 / Ventoy
exFAT), another USB drive, or the Windows partition itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from winbootfix.core.run import CommandError, run
from winbootfix.system import platform
from winbootfix.system.disks import Disk
from winbootfix.system.mounts import MountError, MountManager, system_mounts

log = logging.getLogger(__name__)

WRITABLE_FS = ("vfat", "exfat", "ntfs")


@dataclass
class Target:
    path: Path
    kind: str      # local | boot_usb | usb | windows
    label: str


def _live_medium_target() -> Target | None:
    medium = Path("/run/live/medium")
    for _dev, (mnt, fstype, opts) in system_mounts().items():
        if mnt != str(medium):
            continue
        if fstype not in ("vfat", "exfat"):
            return None
        if "rw" not in opts.split(","):
            try:
                run(["mount", "-o", "remount,rw", str(medium)])
            except CommandError:
                return None
        return Target(medium, "boot_usb", "boot_usb")
    return None


def candidate_targets(disks: list[Disk], mounts: MountManager, windows_root: Path | None = None,
                      windows_writable: bool = False) -> list[Target]:
    """Ordered list of persistent targets. May mount removable partitions read-write."""
    targets: list[Target] = []
    if not platform.is_live_system():
        # Installed Linux: its own disk is persistent, no need to touch removable drives.
        targets.append(Target(Path("/var/lib/winbootfix"), "local", "local"))
        if windows_root is not None and windows_writable:
            targets.append(Target(windows_root / "winbootfix", "windows", "windows"))
        return targets
    live = _live_medium_target()
    if live:
        targets.append(live)
    for disk in disks:
        if not (disk.removable or disk.tran == "usb"):
            continue
        for part in disk.partitions:
            fs = (part.fstype or "").lower()
            if fs not in WRITABLE_FS or part.is_esp:
                continue
            if live and disk.is_boot_medium and (part.label or "") != "Ventoy":
                continue
            try:
                path = mounts.mount(part.path, fs, rw=True, label=f"usb-{part.name}")
            except (MountError, CommandError) as exc:
                log.info("cannot use %s for backups: %s", part.path, exc)
                continue
            kind = "boot_usb" if disk.is_boot_medium else "usb"
            targets.append(Target(path, kind, f"{disk.describe()} - {part.label or part.name}"))
    if windows_root is not None and windows_writable:
        targets.append(Target(windows_root / "winbootfix", "windows", "windows"))
    return targets
