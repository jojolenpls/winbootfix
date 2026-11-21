"""Integration tests on real GPT disk images (loop devices, FAT32 + NTFS through ntfs-3g).

Needs root, losetup, partx, sgdisk, mkfs.fat, mkntfs, ntfs-3g and python3-hivex.
Run: sudo python3 -m pytest tests/loop
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import HAVE_HIVEX, FakeNvram

HERE = Path(__file__).resolve().parent
TOOLS = ("losetup", "partx", "sgdisk", "mkfs.fat", "mkntfs", "ntfs-3g", "blkid")
pytestmark = pytest.mark.skipif(
    os.geteuid() != 0 or not HAVE_HIVEX or any(shutil.which(t) is None for t in TOOLS),
    reason="needs root, python3-hivex and " + ", ".join(TOOLS))


def sh(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def blkid(dev, key):
    return sh("blkid", "-p", "-s", key, "-o", "value", dev)


@pytest.fixture
def disk(tmp_path):
    img = tmp_path / "disk.img"
    dev = sh(str(HERE / "make_image.sh"), str(img), "400")
    mnt = tmp_path / "mnt"
    yield dev, mnt
    subprocess.run(["umount", "-R", str(mnt)], capture_output=True)
    subprocess.run(["partx", "-d", dev], capture_output=True)
    subprocess.run(["losetup", "-d", dev], capture_output=True)


def mount_fat(dev, mnt, ro=False):
    r = subprocess.run(["mount", "-t", "vfat", "-o", "ro" if ro else "rw", dev, str(mnt)], capture_output=True, text=True)
    if r.returncode != 0:
        if "unknown filesystem" not in r.stderr or not shutil.which("fusefat"):
            raise RuntimeError(r.stderr)
        sh("fusefat", "-o", "ro" if ro else "rw+", dev, str(mnt))


def populate(dev, mnt, *, win_kwargs=None, esp_kwargs=None, hibernated=False):
    from tests.helpers import fakewin
    esp_m, win_m = mnt / "esp", mnt / "win"
    esp_m.mkdir(parents=True)
    win_m.mkdir(parents=True)
    mount_fat(f"{dev}p1", esp_m)
    sh("ntfs-3g", f"{dev}p3", str(win_m))
    fakewin.build_windows(win_m, partuuid=blkid(f"{dev}p3", "PART_ENTRY_UUID"), **(win_kwargs or {}))
    fakewin.build_esp(esp_m, **(esp_kwargs or {"bootmgr": False, "other_os": True}))
    if hibernated:
        (win_m / "hiberfil.sys").write_bytes(b"HIBR" + b"\0" * 4092)
    sh("umount", str(esp_m))
    sh("umount", str(win_m))


@pytest.fixture
def system(monkeypatch, disk):
    """Patch what a container cannot provide: UEFI variables, real GPUs."""
    from winbootfix.system import disks, hardware, platform
    dev, mnt = disk
    monkeypatch.setattr(platform, "is_uefi", lambda: True)
    monkeypatch.setattr(platform, "is_live_system", lambda: False)
    monkeypatch.setattr(platform, "secure_boot_state", lambda: "disabled")
    monkeypatch.setattr("winbootfix.boot.diagnose.which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(disks, "boot_medium_device", lambda: None)
    monkeypatch.setattr(hardware, "gpus", lambda devices=None: [hardware.PciDevice("0000:01:00.0", "10de", "2484", "030000", None)])
    real_scan = disks.scan
    monkeypatch.setattr(disks, "scan", lambda *a: [d for d in real_scan(*a) if d.path == dev])
    nv = FakeNvram()
    nv.install(monkeypatch)
    return dev, mnt, nv


def run_cli(tmp_path, *args):
    from winbootfix import cli
    return cli.main(["--lang", "fr", "--yes", "--log", str(tmp_path / "wbf.log"),
                     "--report-dir", str(tmp_path / "reports"), "--backup-dir", str(tmp_path / "backups"), *args])


def mounted(dev, part, mnt, fstype):
    mnt.mkdir(parents=True, exist_ok=True)
    if fstype == "ntfs":
        sh("ntfs-3g", "-o", "ro", f"{dev}p{part}", str(mnt))
    else:
        mount_fat(f"{dev}p{part}", mnt, ro=True)
    return mnt


def test_full_repair_then_restore(system, tmp_path):
    from winbootfix import exitcodes
    from winbootfix.boot.bcd import validate
    from winbootfix.windows.hive import Hive
    dev, mnt, nv = system
    populate(dev, mnt, win_kwargs={"gpu_start": 4, "bad_dlls": True})
    esp_uuid = blkid(f"{dev}p1", "PART_ENTRY_UUID")
    win_uuid = blkid(f"{dev}p3", "PART_ENTRY_UUID")
    nv.disk_partuuids = {(dev, 1): esp_uuid}
    grub = nv.add("debian", 1, esp_uuid, r"\EFI\debian\shimx64.efi")
    nv.order = [grub]

    assert run_cli(tmp_path) == exitcodes.ISSUES_FOUND          # dry run: nothing changes
    assert nv.order == [grub]
    assert run_cli(tmp_path, "--apply") == exitcodes.REPAIRED

    esp = mounted(dev, 1, tmp_path / "check-esp", "vfat")
    try:
        assert (esp / "EFI/Microsoft/Boot/bootmgfw.efi").is_file()
        assert validate.check(validate.read(esp / "EFI/Microsoft/Boot/BCD"), esp_uuid, [win_uuid]) == []
        assert (esp / "EFI/Boot/bootx64.efi").read_bytes() == (esp / "EFI/debian/shimx64.efi").read_bytes()
    finally:
        sh("umount", str(esp))
    assert nv.order[0] == grub and nv.entries[nv.order[1]]["label"] == "Windows Boot Manager"

    win = mounted(dev, 3, tmp_path / "check-win", "ntfs")
    try:
        state = json.loads((win / "winbootfix/state.json").read_text())
        assert state["bcdboot"] and state["keep_bootorder"]
        with Hive(win / "Windows/System32/config/SYSTEM") as h:
            assert h.value(r"ControlSet001\Services\nvlddmkm", "Start") == 3
        with Hive(win / "Windows/System32/config/SOFTWARE") as h:
            assert "winbootfix-post.ps1" in h.value(r"Microsoft\Windows\CurrentVersion\RunOnce", "!winbootfix")
        assert not (win / "Windows/System32/wintab32.dll").exists()
        assert list((win / "winbootfix_quarantine").glob("*/files/Windows/System32/wintab32.dll"))
    finally:
        sh("umount", str(win))

    reports = list((tmp_path / "reports").glob("winbootfix-report-*.txt"))
    assert reports and "Windows Boot Manager" in reports[-1].read_text()

    backup = next((tmp_path / "backups/winbootfix-backups").iterdir())
    assert (backup / "esp.tar.gz").is_file()
    assert run_cli(tmp_path, "restore", str(backup), "--apply") == exitcodes.REPAIRED
    assert nv.order == [grub]
    esp = mounted(dev, 1, tmp_path / "check-esp2", "vfat")
    try:
        assert not (esp / "EFI/Microsoft/Boot/bootmgfw.efi").exists()
        assert (esp / "EFI/debian/shimx64.efi").is_file()
    finally:
        sh("umount", str(esp))
    win = mounted(dev, 3, tmp_path / "check-win2", "ntfs")
    try:
        assert (win / "Windows/System32/wintab32.dll").is_file()
        with Hive(win / "Windows/System32/config/SYSTEM") as h:
            assert h.value(r"ControlSet001\Services\nvlddmkm", "Start") == 4
    finally:
        sh("umount", str(win))


def test_hibernated_windows_boot_repaired_but_windows_untouched(system, tmp_path):
    from winbootfix import exitcodes
    dev, mnt, nv = system
    populate(dev, mnt, win_kwargs={"gpu_start": 4}, hibernated=True)
    nv.disk_partuuids = {(dev, 1): blkid(f"{dev}p1", "PART_ENTRY_UUID")}
    code = run_cli(tmp_path, "--apply")
    assert code == exitcodes.REPAIRED
    report = json.loads(sorted((tmp_path / "reports").glob("*.json"))[-1].read_text())
    ids = {f["id"] for f in report["findings"]}
    assert {"system.hibernated", "system.win_rw_blocked", "boot.nvram_missing"} <= ids
    assert all(not a["id"].startswith("health.") for a in report["actions"])
    win = mounted(dev, 3, tmp_path / "check-win", "ntfs")
    try:
        assert (win / "hiberfil.sys").read_bytes()[:4] == b"HIBR"
        assert not (win / "winbootfix").exists()
    finally:
        sh("umount", str(win))


def test_bitlocker_only_volume(system, tmp_path):
    from winbootfix import exitcodes
    dev, _mnt, _nv = system
    with open(f"{dev}p3", "r+b") as fh:
        fh.seek(3)
        fh.write(b"-FVE-FS-")
    assert run_cli(tmp_path) == exitcodes.BITLOCKER_LOCKED


def test_no_windows(system, tmp_path):
    from winbootfix import exitcodes
    assert run_cli(tmp_path) == exitcodes.NO_WINDOWS
