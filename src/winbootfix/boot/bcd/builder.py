"""Build a BCD store from <Windows>\\System32\\config\\BCD-Template (EXPERIMENTAL).

This reproduces what ``bcdboot <win> /s <esp> /f UEFI`` writes for a GPT
disk. It is marked experimental: the post-repair script regenerates an
official store with bcdboot at the first Windows boot. See docs/BCD.md.
"""

from __future__ import annotations

import shutil
import struct
import uuid
from pathlib import Path

from winbootfix.boot.bcd import constants as C
from winbootfix.boot.bcd import device
from winbootfix.windows.hive import REG_BINARY, REG_DWORD, REG_MULTI_SZ, REG_SZ, Hive, encode_multi_sz, encode_sz


def _guid() -> str:
    return "{" + str(uuid.uuid4()) + "}"


class StoreWriter:
    def __init__(self, hive: Hive):
        self.h = hive

    def obj(self, guid: str, obj_type: int) -> None:
        self.h.set_raw(rf"Objects\{guid}\Description", "Type", REG_DWORD, struct.pack("<I", obj_type))

    def has_obj(self, guid: str) -> bool:
        return self.h.exists(rf"Objects\{guid}\Description")

    def elem(self, guid: str, etype: int, value) -> None:
        fmt = C.element_format(etype)
        if fmt == C.FORMAT_DEVICE:
            vtype, data = REG_BINARY, bytes(value)
        elif fmt in (C.FORMAT_STRING, C.FORMAT_OBJECT):
            vtype, data = REG_SZ, encode_sz(value)
        elif fmt == C.FORMAT_OBJECTLIST:
            vtype, data = REG_MULTI_SZ, encode_multi_sz(list(value))
        elif fmt == C.FORMAT_INTEGER:
            vtype, data = REG_BINARY, struct.pack("<Q", int(value))
        elif fmt == C.FORMAT_BOOLEAN:
            vtype, data = REG_BINARY, b"\x01" if value else b"\x00"
        elif fmt == C.FORMAT_INTEGERLIST:
            vtype, data = REG_BINARY, b"".join(struct.pack("<Q", int(v)) for v in value)
        else:
            raise ValueError(f"unknown element format for {etype:08x}")
        self.h.set_raw(rf"Objects\{guid}\Elements\{C.element_key(etype)}", "Element", vtype, data)


def build(template: Path, out: Path, esp: tuple[str, str], win: tuple[str, str],
          locale: str = "en-US", os_description: str = "Windows 10",
          loader_guid: str | None = None, resume_guid: str | None = None) -> dict[str, str]:
    """Write a new store to *out*. ``esp`` / ``win`` are (partition GUID, disk GUID)."""
    shutil.copyfile(template, out)
    loader = loader_guid or _guid()
    resume = resume_guid or _guid()
    esp_dev = device.encode_gpt_partition(*esp)
    win_dev = device.encode_gpt_partition(*win)

    with Hive(out, write=True, force_dirty=True) as h:
        w = StoreWriter(h)
        if not h.exists("Description"):
            h.set_sz("Description", "KeyName", "BCD00000000")
            h.set_dword("Description", "System", 1)
            h.set_dword("Description", "TreatAsSystem", 1)

        # Inherited settings objects normally come from the template; create the missing ones.
        defaults = [
            (C.GLOBALSETTINGS, C.TYPE_INHERIT_GLOBAL, [C.DBGSETTINGS, C.EMSSETTINGS, C.BADMEMORY]),
            (C.DBGSETTINGS, C.TYPE_INHERIT_GLOBAL, None),
            (C.EMSSETTINGS, C.TYPE_INHERIT_GLOBAL, None),
            (C.BADMEMORY, C.TYPE_INHERIT_GLOBAL, None),
            (C.HYPERVISORSETTINGS, C.TYPE_INHERIT_OSLOADER, None),
            (C.BOOTLOADERSETTINGS, C.TYPE_INHERIT_OSLOADER, [C.GLOBALSETTINGS, C.HYPERVISORSETTINGS]),
            (C.RESUMELOADERSETTINGS, C.TYPE_INHERIT_RESUME, [C.GLOBALSETTINGS]),
        ]
        for guid, otype, inherit in defaults:
            if not w.has_obj(guid):
                w.obj(guid, otype)
                if inherit:
                    w.elem(guid, C.INHERIT, inherit)

        # Windows Boot Manager
        w.obj(C.BOOTMGR, C.TYPE_BOOTMGR)
        w.elem(C.BOOTMGR, C.APP_DEVICE, esp_dev)
        w.elem(C.BOOTMGR, C.APP_PATH, r"\EFI\Microsoft\Boot\bootmgfw.efi")
        w.elem(C.BOOTMGR, C.DESCRIPTION, "Windows Boot Manager")
        w.elem(C.BOOTMGR, C.LOCALE, locale)
        w.elem(C.BOOTMGR, C.INHERIT, [C.GLOBALSETTINGS])
        w.elem(C.BOOTMGR, C.BM_DEFAULT, loader)
        w.elem(C.BOOTMGR, C.BM_RESUME_OBJECT, resume)
        w.elem(C.BOOTMGR, C.BM_DISPLAY_ORDER, [loader])
        w.elem(C.BOOTMGR, C.BM_TOOLS_ORDER, [C.MEMDIAG])
        w.elem(C.BOOTMGR, C.BM_TIMEOUT, 30)

        # Windows Boot Loader
        w.obj(loader, C.TYPE_OSLOADER)
        w.elem(loader, C.APP_DEVICE, win_dev)
        w.elem(loader, C.APP_PATH, r"\Windows\system32\winload.efi")
        w.elem(loader, C.DESCRIPTION, os_description)
        w.elem(loader, C.LOCALE, locale)
        w.elem(loader, C.INHERIT, [C.BOOTLOADERSETTINGS])
        w.elem(loader, C.ISOLATED_CONTEXT, True)
        w.elem(loader, C.ALLOWED_INMEMORY, [0x15000075])
        w.elem(loader, C.OS_DEVICE, win_dev)
        w.elem(loader, C.OS_SYSTEMROOT, r"\Windows")
        w.elem(loader, C.OS_RESUME_OBJECT, resume)
        w.elem(loader, C.OS_NX, 0)               # OptIn
        w.elem(loader, C.OS_BOOTMENUPOLICY, 1)   # Standard

        # Resume from Hibernate
        w.obj(resume, C.TYPE_RESUME)
        w.elem(resume, C.APP_DEVICE, win_dev)
        w.elem(resume, C.APP_PATH, r"\Windows\system32\winresume.efi")
        w.elem(resume, C.DESCRIPTION, "Windows Resume Application")
        w.elem(resume, C.LOCALE, locale)
        w.elem(resume, C.INHERIT, [C.RESUMELOADERSETTINGS])
        w.elem(resume, C.ALLOWED_INMEMORY, [0x15000075])
        w.elem(resume, C.ISOLATED_CONTEXT, True)
        w.elem(resume, C.OS_DEVICE, win_dev)
        w.elem(resume, C.OS_SYSTEMROOT, r"\hiberfil.sys")

        # Memory diagnostic
        w.obj(C.MEMDIAG, C.TYPE_MEMDIAG)
        w.elem(C.MEMDIAG, C.APP_DEVICE, esp_dev)
        w.elem(C.MEMDIAG, C.APP_PATH, r"\EFI\Microsoft\Boot\memtest.efi")
        w.elem(C.MEMDIAG, C.DESCRIPTION, "Windows Memory Diagnostic")
        w.elem(C.MEMDIAG, C.LOCALE, locale)
        w.elem(C.MEMDIAG, C.INHERIT, [C.GLOBALSETTINGS])

        h.commit()
    return {"loader": loader, "resume": resume}
