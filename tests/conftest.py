from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from winbootfix.core.i18n import Translator  # noqa: E402

try:
    import hivex  # noqa: F401
    HAVE_HIVEX = True
except ImportError:
    HAVE_HIVEX = False

needs_hivex = pytest.mark.skipif(not HAVE_HIVEX, reason="python3-hivex not installed")


def make_args(**kw) -> argparse.Namespace:
    base = dict(command="all", target=None, dry_run=False, apply=False, yes=True, backup_dir=None,
                allow_volatile_backup=False, allow_hiberfile_removal=False, expert=False, windows=None,
                esp=None, bitlocker_key=None, windows_first=False, lang="en", report_dir=None, log=None,
                json=False, ui="console", no_color=True, verbose=False)
    base.update(kw)
    return argparse.Namespace(**base)


class FakeNvram:
    """In-memory UEFI boot entries, rendered like `efibootmgr -v`."""

    def __init__(self):
        self.entries: dict[str, dict] = {}
        self.order: list[str] = []

    def add(self, label: str, partnum: int, partuuid: str, loader: str, active: bool = True) -> str:
        num = f"{len(self.entries):04X}"
        while num in self.entries:
            num = f"{int(num, 16) + 1:04X}"
        self.entries[num] = dict(label=label, partnum=partnum, partuuid=partuuid, loader=loader, active=active)
        return num

    def render(self) -> str:
        lines = ["BootCurrent: 0000", "Timeout: 1 seconds", "BootOrder: " + ",".join(self.order)]
        for num, e in self.entries.items():
            star = "*" if e["active"] else " "
            lines.append(f"Boot{num}{star} {e['label']}\tHD({e['partnum']},GPT,{e['partuuid']},0x800,0x100000)/File({e['loader']})")
        return "\n".join(lines) + "\n"

    def install(self, monkeypatch):
        from winbootfix.boot import nvram

        monkeypatch.setattr(nvram, "read_state", lambda: nvram.parse(self.render()))

        def create(disk, partnum, label=nvram.WINDOWS_LABEL, loader=nvram.WINDOWS_LOADER):
            from winbootfix.core import guard
            guard.require_write("nvram")
            disk_uuid = self.disk_partuuids[(disk, partnum)]
            num = self.add(label, partnum, disk_uuid, loader)
            self.order.insert(0, num)
            return num

        def set_order(order):
            self.order = list(order)

        def delete(num):
            self.entries.pop(num, None)
            self.order = [n for n in self.order if n != num]

        monkeypatch.setattr(nvram, "create_entry", create)
        monkeypatch.setattr(nvram, "set_order", set_order)
        monkeypatch.setattr(nvram, "delete_entry", delete)


@pytest.fixture
def t():
    return Translator("en")


@pytest.fixture
def fake_system(tmp_path, monkeypatch, t):
    """A Context wired to plain directories: fake Windows + fake ESP + fake NVRAM."""
    from tests.helpers import fakewin
    from winbootfix.context import Context
    from winbootfix.core.ui import NonInteractiveUI
    from winbootfix.system import hardware, media, platform
    from winbootfix.system.disks import Disk, Partition
    from winbootfix.windows.install import read_install

    def build(*, esp_kwargs=None, win_kwargs=None, args=None, gpus=("10de", "2484")):
        win_root = tmp_path / "win"
        esp_root = tmp_path / "esp"
        backup = tmp_path / "backup"
        backup.mkdir(exist_ok=True)
        win_uuid = "11111111-2222-3333-4444-555555555555"
        esp_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        disk_uuid = "99999999-8888-7777-6666-555555555555"
        fakewin.build_windows(win_root, partuuid=win_uuid, **(win_kwargs or {}))
        fakewin.build_esp(esp_root, **(esp_kwargs or {}))
        disk = Disk("nvme0n1", "/dev/nvme0n1", 512_000_000_000, "gpt", disk_uuid, "Fake NVMe", "nvme", False)
        esp = Partition("nvme0n1p1", "/dev/nvme0n1p1", disk.path, 1, 100_000_000, "vfat", None, None,
                        "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", esp_uuid, None, None, disk)
        winp = Partition("nvme0n1p3", "/dev/nvme0n1p3", disk.path, 3, 400_000_000_000, "ntfs", None, None,
                         "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7", win_uuid, None, None, disk)
        disk.partitions = [esp, winp]
        a = args or make_args()
        ui = NonInteractiveUI(t, assume_yes=a.yes, color=False)
        ctx = Context(a, t, ui)
        ctx.disks = [disk]
        inst = read_install(winp, win_root, winp.path)
        ctx.installs = [inst]
        ctx.install = inst
        ctx.esp = esp
        ctx.esp_mount = lambda rw=False: esp_root
        ctx.win_mount = lambda rw=False: win_root
        ctx.prepare = lambda needs: None
        ctx.release = lambda needs: None
        ctx._targets = [media.Target(backup, "usb", "test")]
        monkeypatch.setattr(platform, "is_uefi", lambda: True)
        monkeypatch.setattr(platform, "secure_boot_state", lambda: "enabled")
        monkeypatch.setattr("winbootfix.boot.diagnose.which", lambda name: "/usr/bin/" + name)
        fake_gpus = [hardware.PciDevice("0000:01:00.0", gpus[0], gpus[1], "030000", None)] if gpus else []
        monkeypatch.setattr(hardware, "gpus", lambda devices=None: fake_gpus)
        nv = FakeNvram()
        nv.disk_partuuids = {(disk.path, 1): esp_uuid}
        nv.install(monkeypatch)
        ctx.nv = nv
        ctx.paths = dict(win=win_root, esp=esp_root, backup=backup, win_uuid=win_uuid, esp_uuid=esp_uuid,
                         disk_uuid=disk_uuid)
        return ctx

    return build
