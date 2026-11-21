import json

from winbootfix.system import disks

LSBLK = {"blockdevices": [
    {"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "size": 512110190592, "pttype": "gpt",
     "ptuuid": "9a1b2c3d-0000-0000-0000-000000000001", "model": "Samsung SSD 980", "tran": "nvme", "rm": False,
     "hotplug": False, "children": [
        {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "type": "part", "size": 104857600, "fstype": "vfat",
         "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "partuuid": "aaaa0000-0000-0000-0000-000000000001"},
        {"name": "nvme0n1p2", "path": "/dev/nvme0n1p2", "type": "part", "size": 16777216, "fstype": None,
         "parttype": "e3c9e316-0b5c-4db8-817d-f92df00215ae"},
        {"name": "nvme0n1p3", "path": "/dev/nvme0n1p3", "type": "part", "size": 500000000000, "fstype": "ntfs",
         "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7", "partuuid": "aaaa0000-0000-0000-0000-000000000003"},
        {"name": "nvme0n1p4", "path": "/dev/nvme0n1p4", "type": "part", "size": 700000000, "fstype": "ntfs",
         "parttype": "de94bba4-06d1-4d40-a16a-bfd50179d6ac"},
        {"name": "nvme0n1p5", "path": "/dev/nvme0n1p5", "type": "part", "size": 300000000, "fstype": "BitLocker",
         "parttype": "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"}]},
    {"name": "sda", "path": "/dev/sda", "type": "disk", "size": 16000000000, "pttype": "dos", "tran": "usb",
     "rm": True, "children": [
        {"name": "sda1", "path": "/dev/sda1", "type": "part", "size": 16000000000, "fstype": "iso9660",
         "parttype": "0x0"}]},
    {"name": "zram0", "path": "/dev/zram0", "type": "disk", "size": 1000},
]}


def test_parse_and_classify():
    ds = disks.parse_lsblk(LSBLK, partnum=lambda n: int(n.rsplit("p", 1)[-1]) if "p" in n else int(n[-1]))
    nvme = ds[0]
    assert nvme.is_gpt and nvme.is_internal and len(nvme.partitions) == 5
    esp, msr, win, winre, bl = nvme.partitions
    assert esp.is_esp and esp.number == 1
    assert msr.is_msr and not msr.maybe_windows
    assert win.maybe_windows and not win.is_esp
    assert winre.is_winre and not winre.maybe_windows
    assert bl.maybe_windows
    assert not ds[1].is_internal
    assert [p.path for p in disks.find_esps(ds)] == ["/dev/nvme0n1p1"]


def test_scan_filters_zram(monkeypatch):
    monkeypatch.setattr(disks, "boot_medium_device", lambda: "/dev/sda1")
    monkeypatch.setattr(disks.os.path, "realpath", lambda p: p)
    ds = disks.scan(json.dumps(LSBLK))
    assert [d.name for d in ds] == ["nvme0n1", "sda"]
    assert ds[1].is_boot_medium
