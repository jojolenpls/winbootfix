"""Read and check a BCD store (existing or freshly generated)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from winbootfix.boot.bcd import constants as C
from winbootfix.boot.bcd import device
from winbootfix.windows.hive import Hive, HiveError


@dataclass
class StoreSummary:
    readable: bool
    error: str | None = None
    has_bootmgr: bool = False
    bootmgr_device: device.DeviceInfo | None = None
    default: str | None = None
    default_type: int | None = None
    default_device: device.DeviceInfo | None = None
    default_osdevice: device.DeviceInfo | None = None
    default_path: str | None = None
    default_systemroot: str | None = None
    objects: list[str] = field(default_factory=list)


def _elem(h: Hive, guid: str, etype: int):
    return h.value(rf"Objects\{guid}\Elements\{C.element_key(etype)}", "Element")


def _find_obj(h: Hive, guid: str) -> str | None:
    want = guid.lower()
    return next((o for o in h.subkeys("Objects") if o.lower() == want), None)


def read(path: Path) -> StoreSummary:
    try:
        with Hive(path) as h:
            objs = h.subkeys("Objects")
            s = StoreSummary(True, objects=objs)
            bm = _find_obj(h, C.BOOTMGR)
            if not bm:
                return s
            s.has_bootmgr = True
            dev = _elem(h, bm, C.APP_DEVICE)
            s.bootmgr_device = device.decode(dev) if isinstance(dev, bytes) else None
            default = _elem(h, bm, C.BM_DEFAULT)
            if isinstance(default, str):
                s.default = default
                obj = _find_obj(h, default)
                if obj:
                    s.default_type = h.value(rf"Objects\{obj}\Description", "Type")
                    d = _elem(h, obj, C.APP_DEVICE)
                    o = _elem(h, obj, C.OS_DEVICE)
                    s.default_device = device.decode(d) if isinstance(d, bytes) else None
                    s.default_osdevice = device.decode(o) if isinstance(o, bytes) else None
                    p = _elem(h, obj, C.APP_PATH)
                    r = _elem(h, obj, C.OS_SYSTEMROOT)
                    s.default_path = p if isinstance(p, str) else None
                    s.default_systemroot = r if isinstance(r, str) else None
            return s
    except HiveError as exc:
        return StoreSummary(False, str(exc))


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip("{}").lower() == b.strip("{}").lower())


def check(s: StoreSummary, esp_partuuid: str | None, windows_partuuids: list[str]) -> list[str]:
    """Return problem codes; an empty list means the store looks usable."""
    if not s.readable:
        return ["unreadable"]
    problems = []
    if not s.has_bootmgr:
        return ["no_bootmgr"]
    if s.bootmgr_device and s.bootmgr_device.is_gpt_partition and esp_partuuid:
        if not _same(s.bootmgr_device.partition_guid, esp_partuuid):
            problems.append("bootmgr_device_mismatch")
    if not s.default:
        problems.append("no_default")
        return problems
    if s.default_type is None:
        problems.append("default_missing")
        return problems
    if s.default_type != C.TYPE_OSLOADER:
        problems.append("default_not_osloader")
        return problems
    for dev, code in ((s.default_device, "device_mismatch"), (s.default_osdevice, "osdevice_mismatch")):
        if dev is None:
            problems.append("device_missing")
        elif dev.is_gpt_partition:
            if windows_partuuids and not any(_same(dev.partition_guid, w) for w in windows_partuuids):
                problems.append(code)
        else:
            problems.append("device_unverifiable")
    if not s.default_path or not s.default_path.lower().endswith("winload.efi"):
        problems.append("path_mismatch")
    if not s.default_systemroot or s.default_systemroot.lower() != r"\windows":
        problems.append("systemroot_mismatch")
    return sorted(set(problems))
