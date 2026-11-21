"""Minimal PE (Portable Executable) parser: architecture, DLL flags, .NET, version resource."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

MACHINE_I386 = 0x014C
MACHINE_AMD64 = 0x8664
MACHINE_ARM64 = 0xAA64
MACHINE_ARMNT = 0x01C4
MACHINE_ARM64EC = 0xA641

MACHINE_NAMES = {MACHINE_I386: "x86", MACHINE_AMD64: "x64", MACHINE_ARM64: "arm64",
                 MACHINE_ARMNT: "arm", MACHINE_ARM64EC: "arm64ec", 0x0200: "ia64"}

IMAGE_FILE_DLL = 0x2000
COMIMAGE_FLAGS_ILONLY = 0x1
COMIMAGE_FLAGS_32BITREQUIRED = 0x2

DIR_IMPORT, DIR_RESOURCE, DIR_SECURITY, DIR_CLR = 1, 2, 4, 14
RT_VERSION = 16


@dataclass
class Section:
    name: str
    vaddr: int
    vsize: int
    raw_off: int
    raw_size: int


@dataclass
class PEInfo:
    valid: bool
    error: str | None = None
    size: int = 0
    machine: int = 0
    characteristics: int = 0
    pe32plus: bool = False
    entry_point: int = 0
    subsystem: int = 0
    directories: list[tuple[int, int]] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    clr_flags: int | None = None
    version: dict[str, str] = field(default_factory=dict)

    @property
    def arch(self) -> str:
        return MACHINE_NAMES.get(self.machine, hex(self.machine))

    @property
    def is_dll(self) -> bool:
        return bool(self.characteristics & IMAGE_FILE_DLL)

    def directory(self, index: int) -> tuple[int, int]:
        return self.directories[index] if index < len(self.directories) else (0, 0)

    @property
    def is_dotnet(self) -> bool:
        return self.directory(DIR_CLR)[0] != 0

    @property
    def is_anycpu(self) -> bool:
        """.NET IL-only assembly that runs as 32 or 64 bit (marked x86 in the header)."""
        return (self.clr_flags is not None and bool(self.clr_flags & COMIMAGE_FLAGS_ILONLY)
                and not self.clr_flags & COMIMAGE_FLAGS_32BITREQUIRED)

    @property
    def is_resource_only(self) -> bool:
        return self.entry_point == 0 and self.directory(DIR_IMPORT)[1] == 0 and not self.is_dotnet

    @property
    def company(self) -> str:
        return self.version.get("CompanyName", "")

    @property
    def is_microsoft(self) -> bool:
        return "microsoft" in self.company.lower()

    def rva_to_offset(self, rva: int) -> int | None:
        for s in self.sections:
            if s.vaddr <= rva < s.vaddr + max(s.vsize, s.raw_size):
                return s.raw_off + (rva - s.vaddr)
        return None


def parse_headers(data: bytes, size: int | None = None) -> PEInfo:
    size = len(data) if size is None else size
    if size == 0:
        return PEInfo(False, "empty file", size)
    if len(data) < 64 or data[:2] != b"MZ":
        return PEInfo(False, "no MZ header", size)
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if e_lfanew + 24 > len(data) or data[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        return PEInfo(False, "no PE signature", size)
    machine, nsec, _ts, _sym, _nsym, opt_size, chars = struct.unpack_from("<HHIIIHH", data, e_lfanew + 4)
    opt = e_lfanew + 24
    info = PEInfo(True, size=size, machine=machine, characteristics=chars)
    if opt_size >= 2 and opt + opt_size <= len(data):
        magic = struct.unpack_from("<H", data, opt)[0]
        info.pe32plus = magic == 0x20B
        if magic in (0x10B, 0x20B):
            info.entry_point = struct.unpack_from("<I", data, opt + 16)[0]
            info.subsystem = struct.unpack_from("<H", data, opt + 68)[0]
            nrva_off, dd_off = (108, 112) if info.pe32plus else (92, 96)
            if opt_size >= nrva_off + 4:
                nrva = min(struct.unpack_from("<I", data, opt + nrva_off)[0], 16)
                for i in range(nrva):
                    off = opt + dd_off + 8 * i
                    if off + 8 > opt + opt_size:
                        break
                    info.directories.append(struct.unpack_from("<II", data, off))
    sec_off = opt + opt_size
    for i in range(min(nsec, 96)):
        off = sec_off + 40 * i
        if off + 40 > len(data):
            break
        name = data[off:off + 8].rstrip(b"\0").decode("ascii", "replace")
        vsize, vaddr, rsize, roff = struct.unpack_from("<IIII", data, off + 8)
        info.sections.append(Section(name, vaddr, vsize, roff, rsize))
    return info


def _read_at(fh, offset: int, length: int) -> bytes:
    fh.seek(offset)
    return fh.read(length)


def parse_file(path: Path, with_version: bool = False) -> PEInfo:
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(4096)
            if len(head) >= 64 and head[:2] == b"MZ":
                e_lfanew = struct.unpack_from("<I", head, 0x3C)[0]
                if e_lfanew + 1024 > len(head) and e_lfanew < 1 << 20:
                    head = head + _read_at(fh, len(head), e_lfanew + 4096 - len(head))
            info = parse_headers(head, size)
            if not info.valid:
                return info
            rva, csize = info.directory(DIR_CLR)
            if rva and csize >= 20:
                off = info.rva_to_offset(rva)
                if off is not None:
                    blob = _read_at(fh, off, 20)
                    if len(blob) == 20:
                        info.clr_flags = struct.unpack_from("<I", blob, 16)[0]
            if with_version:
                info.version = _read_version(fh, info)
    except OSError as exc:
        return PEInfo(False, str(exc))
    return info


def _read_version(fh, info: PEInfo) -> dict[str, str]:
    rva, size = info.directory(DIR_RESOURCE)
    if not rva or not size or size > 64 << 20:
        return {}
    base = info.rva_to_offset(rva)
    if base is None:
        return {}
    rsrc = _read_at(fh, base, size)

    def entries(off: int) -> list[tuple[int, int]]:
        if off + 16 > len(rsrc):
            return []
        named, ids = struct.unpack_from("<HH", rsrc, off + 12)
        out = []
        for i in range(named + ids):
            e = off + 16 + 8 * i
            if e + 8 > len(rsrc):
                break
            out.append(struct.unpack_from("<II", rsrc, e))
        return out

    try:
        level1 = [e for e in entries(0) if e[0] == RT_VERSION]
        if not level1 or not level1[0][1] & 0x80000000:
            return {}
        names = entries(level1[0][1] & 0x7FFFFFFF)
        if not names:
            return {}
        sub = names[0][1]
        if sub & 0x80000000:
            langs = entries(sub & 0x7FFFFFFF)
            if not langs:
                return {}
            sub = langs[0][1]
        data_rva, data_size = struct.unpack_from("<II", rsrc, sub & 0x7FFFFFFF)
        off = info.rva_to_offset(data_rva)
        if off is None:
            return {}
        return parse_version_info(_read_at(fh, off, min(data_size, 1 << 20)))
    except struct.error:
        return {}


def _align4(n: int) -> int:
    return (n + 3) & ~3


def _blocks(data: bytes, start: int, end: int):
    off = start
    while off + 6 <= end:
        length, vlen, vtype = struct.unpack_from("<HHH", data, off)
        if length == 0:
            break
        key_start = off + 6
        key_end = key_start
        while key_end + 1 < len(data) and data[key_end:key_end + 2] != b"\0\0":
            key_end += 2
        key = data[key_start:key_end].decode("utf-16-le", "replace")
        val_start = _align4(key_end + 2)
        val_len = vlen * 2 if vtype == 1 else vlen
        value = data[val_start:val_start + val_len]
        children_start = _align4(val_start + val_len)
        block_end = min(off + length, end)
        yield key, vtype, value, children_start, block_end
        off = _align4(off + length)


def parse_version_info(data: bytes) -> dict[str, str]:
    """Return the StringFileInfo strings (first string table) + FileVersion from the fixed info."""
    out: dict[str, str] = {}
    for key, _t, value, cstart, cend in _blocks(data, 0, len(data)):
        if key != "VS_VERSION_INFO":
            continue
        if len(value) >= 16 and struct.unpack_from("<I", value, 0)[0] == 0xFEEF04BD:
            ms, ls = struct.unpack_from("<II", value, 8)
            out["FixedFileVersion"] = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        for k2, _t2, _v2, c2s, c2e in _blocks(data, cstart, cend):
            if k2 != "StringFileInfo":
                continue
            for _table, _t3, _v3, c3s, c3e in _blocks(data, c2s, c2e):
                for name, _t4, val, _c4s, _c4e in _blocks(data, c3s, c3e):
                    out.setdefault(name, val.decode("utf-16-le", "replace").rstrip("\0"))
                break
        break
    return out


def security_blob(path: Path, max_size: int = 1 << 20) -> bytes:
    """Raw Authenticode certificate table (empty if unsigned)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
            info = parse_headers(head, path.stat().st_size)
            if not info.valid:
                return b""
            off, size = info.directory(DIR_SECURITY)  # file offset, not an RVA
            if not off or not size or size > max_size:
                return b""
            return _read_at(fh, off, size)
    except OSError:
        return b""
