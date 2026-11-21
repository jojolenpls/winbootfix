"""Low-level NTFS / BitLocker inspection of a volume's first sectors.

Nothing here needs the volume to be mounted.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

BITLOCKER_SIGNATURE = b"-FVE-FS-"
NTFS_SIGNATURE = b"NTFS    "
VOLUME_DIRTY = 0x0001
HIBERNATION_SIGNATURES = (b"hibr", b"HIBR", b"wake", b"WAKE", b"RSTR", b"rstr")


@dataclass
class VolumeInfo:
    kind: str                 # ntfs | bitlocker | other
    dirty: bool | None = None
    ntfs_version: str | None = None
    error: str | None = None


def classify_boot_sector(sector: bytes) -> str:
    oem = sector[3:11]
    if oem == BITLOCKER_SIGNATURE:
        return "bitlocker"
    if oem == NTFS_SIGNATURE:
        return "ntfs"
    return "other"


def _apply_fixups(record: bytearray, sector_size: int) -> None:
    usa_off, usa_count = struct.unpack_from("<HH", record, 4)
    if usa_count < 2:
        return
    usn = record[usa_off:usa_off + 2]
    for i in range(1, usa_count):
        end = i * sector_size - 2
        if end + 2 > len(record):
            break
        if record[end:end + 2] != usn:
            raise ValueError("NTFS fixup mismatch (corrupted MFT record)")
        record[end:end + 2] = record[usa_off + 2 * i:usa_off + 2 * i + 2]


def parse_geometry(boot: bytes) -> tuple[int, int, int, int]:
    """Return (bytes_per_sector, cluster_size, mft_offset, mft_record_size)."""
    bps = struct.unpack_from("<H", boot, 0x0B)[0]
    spc = boot[0x0D]
    if spc > 0x80:  # cluster size encoded as 2^(256 - n) sectors
        spc = 1 << (256 - spc)
    cluster = bps * spc
    mft_lcn = struct.unpack_from("<Q", boot, 0x30)[0]
    cpr = struct.unpack_from("<b", boot, 0x40)[0]
    record_size = (1 << -cpr) if cpr < 0 else cpr * cluster
    return bps, cluster, mft_lcn * cluster, record_size


def volume_flags_from_record(record: bytes, sector_size: int) -> tuple[int, str]:
    rec = bytearray(record)
    if rec[:4] != b"FILE":
        raise ValueError("$Volume MFT record has no FILE signature")
    _apply_fixups(rec, sector_size)
    off = struct.unpack_from("<H", rec, 0x14)[0]
    while off + 8 <= len(rec):
        atype, alen = struct.unpack_from("<II", rec, off)
        if atype == 0xFFFFFFFF or alen == 0:
            break
        if atype == 0x70 and rec[off + 8] == 0:  # $VOLUME_INFORMATION, resident
            clen, coff = struct.unpack_from("<IH", rec, off + 0x10)
            content = rec[off + coff: off + coff + clen]
            major, minor, flags = struct.unpack_from("<BBH", content, 8)
            return flags, f"{major}.{minor}"
        off += alen
    raise ValueError("$VOLUME_INFORMATION attribute not found")


def inspect_volume(device: str) -> VolumeInfo:
    kind = "other"
    try:
        with open(device, "rb") as fh:
            boot = fh.read(512)
            kind = classify_boot_sector(boot)
            if kind != "ntfs":
                return VolumeInfo(kind)
            bps, _cluster, mft_off, rec_size = parse_geometry(boot)
            fh.seek(mft_off + 3 * rec_size)  # record 3 = $Volume
            record = fh.read(rec_size)
        flags, version = volume_flags_from_record(record, bps)
        return VolumeInfo("ntfs", dirty=bool(flags & VOLUME_DIRTY), ntfs_version=version)
    except (OSError, ValueError, struct.error) as exc:
        return VolumeInfo(kind, error=str(exc))


def is_hibernation_header(head: bytes) -> bool:
    return head[:4] in HIBERNATION_SIGNATURES
