"""Mounting helpers. Read-only by default; read-write only inside a confirmed action."""

from __future__ import annotations

import atexit
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from winbootfix.core import guard
from winbootfix.core.run import CommandError, run, which

log = logging.getLogger(__name__)

BASE = Path("/run/winbootfix/mnt")

# ntfs-3g exit codes (see ntfs-3g's mount helper)
NTFS3G_HIBERNATED = 14
NTFS3G_UNCLEAN = 15


class MountError(RuntimeError):
    def __init__(self, message: str, reason: str = "error"):
        super().__init__(message)
        self.reason = reason  # error | hibernated | unclean | unsupported


@dataclass
class Mount:
    device: str
    path: Path
    fstype: str
    rw: bool
    ours: bool


def system_mounts() -> dict[str, tuple[str, str, str]]:
    """device -> (mountpoint, fstype, options) from /proc/mounts."""
    out = {}
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            src, mnt, fstype, opts = line.split()[:4]
            mnt = mnt.replace("\\040", " ")
            if src.startswith("/dev/"):
                out[os.path.realpath(src)] = (mnt, fstype, opts)
    except OSError:
        pass
    return out


class MountManager:
    def __init__(self):
        self.mounts: dict[str, Mount] = {}
        atexit.register(self.cleanup)

    def _target(self, device: str, label: str | None) -> Path:
        name = label or Path(device).name
        path = BASE / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def mount(self, device: str, fstype: str, rw: bool = False, label: str | None = None,
              allow_hiberfile_removal: bool = False) -> Path:
        key = os.path.realpath(device) if device.startswith("/dev/") else device
        existing = self.mounts.get(key)
        if existing and (existing.rw or not rw):
            return existing.path
        if rw:
            guard.require_write(f"mount {device} read-write")
        sysm = system_mounts().get(key)
        if sysm and not existing:
            mnt, sfs, opts = sysm
            is_rw = "rw" in opts.split(",")
            if not rw or is_rw:
                self.mounts[key] = Mount(device, Path(mnt), sfs, is_rw, ours=False)
                return Path(mnt)
            raise MountError(f"{device} is already mounted read-only on {mnt}; unmount it first")
        if existing:
            self.unmount(key)
        target = self._target(device, label)
        if fstype in ("ntfs", "ntfs-3g", "fuseblk"):
            self._mount_ntfs(device, target, rw, allow_hiberfile_removal)
            fstype = "ntfs"
        elif fstype == "vfat":
            fstype = self._mount_vfat(device, target, rw)
        elif fstype in ("exfat",):
            run(["mount", "-t", "exfat", "-o", "rw" if rw else "ro", device, str(target)])
        else:
            raise MountError(f"unsupported filesystem {fstype} on {device}", "unsupported")
        self.mounts[key] = Mount(device, target, fstype, rw, ours=True)
        log.info("mounted %s on %s (%s, %s)", device, target, fstype, "rw" if rw else "ro")
        return target

    def _mount_vfat(self, device: str, target: Path, rw: bool) -> str:
        opts = "rw" if rw else "ro"
        try:
            run(["mount", "-t", "vfat", "-o", f"{opts},utf8,shortname=mixed", device, str(target)])
            return "vfat"
        except CommandError as exc:
            # Kernels without FAT support (some containers, WSL): FUSE fallback
            if "unknown filesystem" not in (exc.stderr + exc.stdout) or not which("fusefat"):
                raise
        run(["fusefat", "-o", "rw+" if rw else "ro", device, str(target)])
        return "vfat-fuse"

    def _mount_ntfs(self, device: str, target: Path, rw: bool, allow_hiberfile_removal: bool) -> None:
        if which("ntfs-3g"):
            opts = ["rw", "windows_names"] if rw else ["ro"]
            if rw and allow_hiberfile_removal:
                opts.append("remove_hiberfile")
            try:
                run(["ntfs-3g", "-o", ",".join(opts), device, str(target)])
                return
            except CommandError as exc:
                if exc.returncode == NTFS3G_HIBERNATED:
                    raise MountError(str(exc), "hibernated") from exc
                if exc.returncode == NTFS3G_UNCLEAN:
                    raise MountError(str(exc), "unclean") from exc
                raise MountError(str(exc)) from exc
        if rw:
            raise MountError("ntfs-3g is required to write to NTFS", "unsupported")
        run(["mount", "-t", "ntfs3", "-o", "ro", device, str(target)])

    def remount_ro(self, device: str) -> None:
        key = os.path.realpath(device) if device.startswith("/dev/") else device
        m = self.mounts.get(key)
        if not m or not m.rw or not m.ours:
            return
        run(["sync"], check=False)
        if m.fstype == "vfat":
            run(["mount", "-o", "remount,ro", str(m.path)])
            m.rw = False
        else:
            label = m.path.name
            self.unmount(key)
            self.mount(device, "vfat" if m.fstype == "vfat-fuse" else m.fstype, rw=False, label=label)

    def unmount_device(self, device: str) -> None:
        self.unmount(os.path.realpath(device) if device.startswith("/dev/") else device)

    def unmount(self, key: str) -> None:
        m = self.mounts.pop(key, None)
        if not m or not m.ours:
            return
        run(["sync"], check=False)
        try:
            run(["umount", str(m.path)])
        except CommandError:
            run(["umount", "-l", str(m.path)], check=False)
        try:
            m.path.rmdir()
        except OSError:
            pass

    def cleanup(self) -> None:
        for key in list(self.mounts):
            try:
                self.unmount(key)
            except Exception:  # noqa: BLE001
                log.exception("cannot unmount %s", key)
