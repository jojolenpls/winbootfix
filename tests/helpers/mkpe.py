"""Build small but structurally valid PE files for tests."""

from __future__ import annotations

import struct

MACHINE_I386 = 0x14C
MACHINE_AMD64 = 0x8664


def _version_resource(strings: dict[str, str]) -> bytes:
    def block(key: str, value: bytes, vtype: int, children: bytes = b"", value_words: bool = False) -> bytes:
        key_b = (key + "\0").encode("utf-16-le")
        head_len = 6 + len(key_b)
        pad1 = (-head_len) % 4
        body = value + b"\0" * ((-len(value)) % 4) + children
        vlen = len(value) // 2 if value_words else len(value)
        total = head_len + pad1 + body.__len__()
        return struct.pack("<HHH", total, vlen, vtype) + key_b + b"\0" * pad1 + body

    entries = b""
    for k, v in strings.items():
        entries += block(k, (v + "\0").encode("utf-16-le"), 1, value_words=True)
    table = block("040904B0", b"", 1, entries)
    sfi = block("StringFileInfo", b"", 1, table)
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x10000, 0x000A0000, 0x4A610000, 0, 0, 0x3F, 0, 4, 2, 0, 0, 0)
    return block("VS_VERSION_INFO", fixed, 0, sfi)


def build_pe(machine: int = MACHINE_AMD64, dll: bool = True, entry_point: int = 0x1000,
             imports: bool = True, clr_flags: int | None = None, version: dict[str, str] | None = None,
             security: bytes = b"") -> bytes:
    pe32plus = machine != MACHINE_I386
    opt_size = 240 if pe32plus else 224
    e_lfanew = 0x80
    nsec = 2
    headers_end = e_lfanew + 24 + opt_size + 40 * nsec
    text_off, text_rva, text_size = 0x200, 0x1000, 0x200
    rsrc_off, rsrc_rva = 0x400, 0x2000

    text = bytearray(text_size)
    if clr_flags is not None:
        struct.pack_into("<IHHIII", text, 0, 72, 2, 5, 0, 0, clr_flags)

    rsrc = b""
    if version:
        data = _version_resource(version)
        # root dir -> type 16 -> name 1 -> lang 0x409 -> data entry
        d_root, d_type, d_lang = 0, 24, 48
        entry_off = 72
        data_off = 88
        r = bytearray(data_off)
        struct.pack_into("<IIHHHH", r, d_root, 0, 0, 0, 0, 0, 1)
        struct.pack_into("<II", r, d_root + 16, 16, 0x80000000 | d_type)
        struct.pack_into("<IIHHHH", r, d_type, 0, 0, 0, 0, 0, 1)
        struct.pack_into("<II", r, d_type + 16, 1, 0x80000000 | d_lang)
        struct.pack_into("<IIHHHH", r, d_lang, 0, 0, 0, 0, 0, 1)
        struct.pack_into("<II", r, d_lang + 16, 0x409, entry_off)
        struct.pack_into("<IIII", r, entry_off, rsrc_rva + data_off, len(data), 0, 0)
        rsrc = bytes(r) + data
    rsrc_size = max(0x200, (len(rsrc) + 0x1FF) & ~0x1FF)
    rsrc = rsrc + b"\0" * (rsrc_size - len(rsrc))

    sec_off = rsrc_off + rsrc_size
    out = bytearray(sec_off)
    out[0:2] = b"MZ"
    struct.pack_into("<I", out, 0x3C, e_lfanew)
    out[e_lfanew:e_lfanew + 4] = b"PE\0\0"
    chars = 0x0002 | (0x2000 if dll else 0) | (0 if pe32plus else 0x0100)
    struct.pack_into("<HHIIIHH", out, e_lfanew + 4, machine, nsec, 0, 0, 0, opt_size, chars)
    opt = e_lfanew + 24
    struct.pack_into("<H", out, opt, 0x20B if pe32plus else 0x10B)
    struct.pack_into("<I", out, opt + 16, entry_point)
    struct.pack_into("<H", out, opt + 68, 2)
    nrva_off, dd_off = (108, 112) if pe32plus else (92, 96)
    struct.pack_into("<I", out, opt + nrva_off, 16)
    dirs = {}
    if imports:
        dirs[1] = (text_rva + 0x100, 40)
    if version:
        dirs[2] = (rsrc_rva, len(rsrc))
    if security:
        dirs[4] = (sec_off, len(security))
    if clr_flags is not None:
        dirs[14] = (text_rva, 72)
    for idx, (a, b) in dirs.items():
        struct.pack_into("<II", out, opt + dd_off + 8 * idx, a, b)
    s = opt + opt_size
    struct.pack_into("<8sIIII", out, s, b".text", text_size, text_rva, text_size, text_off)
    struct.pack_into("<8sIIII", out, s + 40, b".rsrc", rsrc_size, rsrc_rva, rsrc_size, rsrc_off)
    assert headers_end <= text_off
    out[text_off:text_off + text_size] = text
    out[rsrc_off:rsrc_off + rsrc_size] = rsrc
    return bytes(out) + security


def ms_pe(name: str, machine: int = MACHINE_AMD64, **kw) -> bytes:
    return build_pe(machine, version={"CompanyName": "Microsoft Corporation", "OriginalFilename": name,
                                      "InternalName": name.split(".")[0], "FileVersion": "10.0.19041.1"}, **kw)
