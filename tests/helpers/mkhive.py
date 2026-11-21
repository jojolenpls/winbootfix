"""Create an empty, valid registry hive file (regf) that hivex can open and fill.

hivex cannot create hives from scratch, so tests build a minimal one:
base block + one hbin holding a root key (nk) and a security cell (sk).
"""

from __future__ import annotations

import struct
from pathlib import Path

NO_CELL = 0xFFFFFFFF


def _checksum(block: bytes) -> int:
    x = 0
    for (v,) in struct.iter_unpack("<I", block[:508]):
        x ^= v
    if x == 0xFFFFFFFF:
        return 0xFFFFFFFE
    return x or 1


def _cell(payload: bytes) -> bytes:
    size = (len(payload) + 4 + 7) & ~7
    return struct.pack("<i", -size) + payload + b"\0" * (size - 4 - len(payload))


def make_hive(path: Path, root_name: str = "ROOT") -> Path:
    hbin_size = 4096
    root_off = 0x20
    name = root_name.encode("ascii")
    nk_len = 76 + len(name)
    nk_cell_size = (nk_len + 4 + 7) & ~7
    sk_off = root_off + nk_cell_size
    nk = struct.pack(
        "<2sHQIIIIIIIIIIIIIIIHH",
        b"nk", 0x2C, 0, 0, NO_CELL, 0, 0, NO_CELL, NO_CELL, 0, NO_CELL, sk_off, NO_CELL,
        0, 0, 0, 0, 0, len(name), 0,
    ) + name
    descriptor = struct.pack("<BBHIIII", 1, 0, 0x8004, 0, 0, 0, 0)  # self-relative, NULL DACL
    sk = struct.pack("<2sHIIII", b"sk", 0, sk_off, sk_off, 1, len(descriptor)) + descriptor
    cells = _cell(nk) + _cell(sk)
    free = hbin_size - 0x20 - len(cells)
    hbin = struct.pack("<4sIIQQI", b"hbin", 0, hbin_size, 0, 0, 0) + cells + struct.pack("<i", free) + b"\0" * (free - 4)
    assert len(hbin) == hbin_size
    base = bytearray(4096)
    struct.pack_into("<4sIIQIIIIII", base, 0, b"regf", 1, 1, 0, 1, 3, 0, 1, root_off, hbin_size)
    struct.pack_into("<I", base, 0x2C, 1)
    struct.pack_into("<I", base, 508, _checksum(bytes(base)))
    path.write_bytes(bytes(base) + hbin)
    return path
