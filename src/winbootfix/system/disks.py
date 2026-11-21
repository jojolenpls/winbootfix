"""Disk and partition discovery (lsblk JSON + sysfs)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from winbootfix.core.run import run

ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
MSR_GUID = "e3c9e316-0b5c-4db8-817d-f92df00215ae"
BASIC_DATA_GUID = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
WINRE_GUID = "de94bba4-06d1-4d40-a16a-bfd50179d6ac"
LDM_GUIDS = {"5808c8aa-7e8f-42e0-85d2-e1e90434cfb3", "af9b60a0-1431-4f62-bc68-3311714a69ad"}

LSBLK_COLUMNS = ("NAME,PATH,PKNAME,TYPE,SIZE,FSTYPE,LABEL,UUID,PARTTYPE,PARTUUID,PARTLABEL,"
                 "PTUUID,PTTYPE,MOUNTPOINT,RM,HOTPLUG,TRAN,MODEL,RO")


@dataclass
class Partition:
    name: str
    path: str
    disk_path: str
    number: int | None
    size: int
    fstype: str | None
    label: str | None
    uuid: str | None
    parttype: str | None
    partuuid: str | None
    partlabel: str | None
    mountpoint: str | None
    disk: Disk | None = field(default=None, repr=False)

    @property
    def is_esp(self) -> bool:
        pt = (self.parttype or "").lower()
        return pt == ESP_GUID or pt == "0xef"

    @property
    def is_msr(self) -> bool:
        return (self.parttype or "").lower() == MSR_GUID

    @property
    def is_winre(self) -> bool:
        return (self.parttype or "").lower() in (WINRE_GUID, "0x27")

    @property
    def maybe_windows(self) -> bool:
        """NTFS or BitLocker data partition that could hold Windows."""
        if self.is_esp or self.is_msr or self.is_winre:
            return False
        return (self.fstype or "").lower() in ("ntfs", "bitlocker", "")


@dataclass
class Disk:
    name: str
    path: str
    size: int
    pttype: str | None
    ptuuid: str | None
    model: str | None
    tran: str | None
    removable: bool
    partitions: list[Partition] = field(default_factory=list)
    is_boot_medium: bool = False

    @property
    def is_gpt(self) -> bool:
        return self.pttype == "gpt"

    @property
    def is_internal(self) -> bool:
        return not self.removable and (self.tran or "") not in ("usb",) and not self.is_boot_medium

    def describe(self) -> str:
        size = f"{self.size / 1e9:.0f} GB" if self.size >= 1e9 else f"{self.size / 1e6:.0f} MB"
        model = (self.model or "").strip() or self.name
        kind = (self.tran or "").upper() or ("NVMe" if "nvme" in self.name else "")
        return f"{model} ({size}{', ' + kind if kind else ''})"


def _bool(v) -> bool:
    return v in (True, 1, "1", "true")


def _partition_number(name: str) -> int | None:
    try:
        return int(Path(f"/sys/class/block/{name}/partition").read_text().strip())
    except (OSError, ValueError):
        pass
    digits = ""
    for ch in reversed(name):
        if ch.isdigit():
            digits = ch + digits
        else:
            break
    return int(digits) if digits else None


def parse_lsblk(data: dict, partnum=_partition_number) -> list[Disk]:
    disks: list[Disk] = []

    def walk(dev: dict, parent: Disk | None):
        dtype = dev.get("type")
        if dtype == "disk" or (dtype == "loop" and dev.get("children")):
            disk = Disk(
                name=dev["name"], path=dev.get("path") or f"/dev/{dev['name']}",
                size=int(dev.get("size") or 0), pttype=dev.get("pttype"),
                ptuuid=(dev.get("ptuuid") or None), model=dev.get("model"),
                tran=dev.get("tran"), removable=_bool(dev.get("rm")) or _bool(dev.get("hotplug")),
            )
            disks.append(disk)
            for child in dev.get("children") or []:
                walk(child, disk)
        elif dtype == "part" and parent is not None:
            part = Partition(
                name=dev["name"], path=dev.get("path") or f"/dev/{dev['name']}",
                disk_path=parent.path, number=partnum(dev["name"]),
                size=int(dev.get("size") or 0), fstype=(dev.get("fstype") or None),
                label=dev.get("label"), uuid=dev.get("uuid"),
                parttype=(dev.get("parttype") or None), partuuid=(dev.get("partuuid") or None),
                partlabel=dev.get("partlabel"), mountpoint=dev.get("mountpoint"), disk=parent,
            )
            parent.partitions.append(part)
        else:
            for child in dev.get("children") or []:
                walk(child, parent)

    for dev in data.get("blockdevices", []):
        walk(dev, None)
    return disks


def boot_medium_device() -> str | None:
    """Block device that holds the running live system (/run/live/medium)."""
    try:
        for line in Path("/proc/mounts").read_text().splitlines():
            src, mnt = line.split()[:2]
            if mnt == "/run/live/medium" and src.startswith("/dev/"):
                return src
    except OSError:
        pass
    return None


def blkid_probe(device: str) -> dict[str, str]:
    """Low-level probe (works without udev, e.g. in containers or minimal rescue systems)."""
    try:
        out = run(["blkid", "-p", "-o", "export", device], check=False).stdout
    except Exception:  # noqa: BLE001 - blkid missing
        return {}
    info = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info[k] = v.replace("\\ ", " ")
    return info


def fill_missing(disks: list[Disk], probe=blkid_probe) -> None:
    """lsblk takes partition types and UUIDs from the udev database; probe directly when it is empty."""
    for d in disks:
        if not d.pttype or not d.ptuuid:
            info = probe(d.path)
            d.pttype = d.pttype or (info.get("PTTYPE") or None)
            d.ptuuid = d.ptuuid or (info.get("PTUUID") or None)
        for p in d.partitions:
            if p.parttype and p.partuuid and p.fstype:
                continue
            info = probe(p.path)
            p.fstype = p.fstype or (info.get("TYPE") or None)
            p.parttype = p.parttype or (info.get("PART_ENTRY_TYPE") or None)
            p.partuuid = p.partuuid or (info.get("PART_ENTRY_UUID") or None)
            p.label = p.label or info.get("LABEL")
            p.uuid = p.uuid or info.get("UUID")
            if p.number is None and info.get("PART_ENTRY_NUMBER", "").isdigit():
                p.number = int(info["PART_ENTRY_NUMBER"])


def scan(lsblk_json: str | None = None) -> list[Disk]:
    probe = lsblk_json is None
    if lsblk_json is None:
        lsblk_json = run(["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS]).stdout
    disks = parse_lsblk(json.loads(lsblk_json))
    if probe:
        fill_missing(disks)
    medium = boot_medium_device()
    if medium:
        real = os.path.realpath(medium)
        for d in disks:
            if d.path == real or any(p.path == real for p in d.partitions):
                d.is_boot_medium = True
    # Ventoy: the ISO is loop-mounted from a partition labelled "Ventoy"
    for d in disks:
        if any((p.label or "") == "Ventoy" for p in d.partitions) and d.removable:
            d.is_boot_medium = d.is_boot_medium or Path("/run/live/medium").is_dir()
    return [d for d in disks if not d.name.startswith(("zram", "ram", "sr"))]


def all_partitions(disks: list[Disk]) -> list[Partition]:
    return [p for d in disks for p in d.partitions]


def find_esps(disks: list[Disk]) -> list[Partition]:
    return [p for p in all_partitions(disks)
            if p.is_esp and (p.fstype or "vfat") == "vfat" and p.disk and not p.disk.is_boot_medium]
