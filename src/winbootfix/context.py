"""Session state shared by all modules."""

from __future__ import annotations

import logging
from pathlib import Path

from winbootfix.core import guard
from winbootfix.core.backup import BackupManager
from winbootfix.core.quarantine import Quarantine
from winbootfix.core.report import Report
from winbootfix.core.run import run
from winbootfix.system import media
from winbootfix.system.mounts import MountError, MountManager

log = logging.getLogger(__name__)


class Context:
    def __init__(self, args, t, ui):
        self.args = args
        self.t = t
        self.ui = ui
        self.mounts = MountManager()
        self.report = Report(t)
        self.backups = BackupManager(self)
        self.disks = []
        self.installs = []
        self.install = None
        self.esps = []
        self.esp = None
        self.boot_state = None
        self.flags: dict = {}
        self.keep_win_rw = False
        self._quarantine: Quarantine | None = None
        self._targets: list[media.Target] | None = None

    # mounts ------------------------------------------------------------------
    def esp_mount(self, rw: bool = False) -> Path:
        if self.esp is None:
            raise RuntimeError("no EFI system partition selected")
        return self.mounts.mount(self.esp.path, "vfat", rw=rw, label=f"esp-{self.esp.name}")

    def win_mount(self, rw: bool = False) -> Path:
        inst = self.install
        if inst is None:
            raise RuntimeError("no Windows installation selected")
        if rw and inst.hibernated and not self.args.allow_hiberfile_removal:
            raise MountError(self.t("error.hibernated_rw"), "hibernated")
        if rw and inst.bitlocker and not self.flags.get("bitlocker_rw"):
            raise MountError(self.t("error.bitlocker_ro"), "unsupported")
        path = self.mounts.mount(inst.device, "ntfs", rw=rw, label=f"win-{inst.partition.name}",
                                 allow_hiberfile_removal=self.args.allow_hiberfile_removal)
        if rw and inst.hibernated:
            inst.hibernated = False  # ntfs-3g removed the hibernation file
        return path

    def prepare(self, needs: frozenset[str]) -> None:
        if "esp_rw" in needs:
            self.esp_mount(rw=True)
        if "win_rw" in needs:
            self.win_mount(rw=True)
        if "nvram" in needs:
            self._efivars_rw()

    def release(self, needs: frozenset[str]) -> None:
        if "esp_rw" in needs and self.esp is not None:
            self.mounts.remount_ro(self.esp.path)
        if "win_rw" in needs and self.install is not None and not self.keep_win_rw:
            self.mounts.remount_ro(self.install.device)

    def _efivars_rw(self) -> None:
        try:
            with open("/proc/mounts") as fh:
                for line in fh:
                    parts = line.split()
                    if parts[2] == "efivarfs" and "ro" in parts[3].split(","):
                        guard.require_write("efivarfs remount")
                        run(["mount", "-o", "remount,rw", parts[1]])
        except OSError:
            pass

    # backups / quarantine -----------------------------------------------------
    def windows_writable(self) -> bool:
        inst = self.install
        return bool(inst and not inst.hibernated and not inst.dirty and
                    (not inst.bitlocker or self.flags.get("bitlocker_rw")))

    def persistent_targets(self) -> list[media.Target]:
        if self._targets is None:
            root = self.install.root if self.install else None
            self._targets = media.candidate_targets(self.disks, self.mounts, root, self.windows_writable())
        return self._targets

    def quarantine(self) -> Quarantine:
        if self._quarantine is None:
            self._quarantine = Quarantine(self.win_mount(rw=True))
        return self._quarantine

    def has_quarantine(self) -> bool:
        return self._quarantine is not None and bool(self._quarantine.entries)

    def close(self) -> None:
        self.mounts.cleanup()
