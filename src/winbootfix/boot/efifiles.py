"""Windows boot files on the EFI system partition (what bcdboot copies)."""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from winbootfix.core import guard
from winbootfix.system import winpath
from winbootfix.windows import pe

log = logging.getLogger(__name__)

MS_BOOT = "EFI/Microsoft/Boot"
BOOTMGR = f"{MS_BOOT}/bootmgfw.efi"
BCD = f"{MS_BOOT}/BCD"
FALLBACK = "EFI/Boot/bootx64.efi"
_EX_RX = re.compile(r"_EX(?=\.)", re.I)


@dataclass
class EspStatus:
    bootmgr: Path | None
    bootmgr_valid: bool
    bcd: Path | None
    fallback: Path | None
    fallback_is_microsoft: bool
    other_loaders: list[str] = field(default_factory=list)


def is_microsoft_bootmgr(path: Path) -> bool:
    """True for a Windows boot manager (never for shim, GRUB or systemd-boot)."""
    from winbootfix.boot import certs

    info = pe.parse_file(path, with_version=True)
    if not info.valid:
        return False
    name = (info.version.get("OriginalFilename", "") + info.version.get("InternalName", "")).lower()
    if info.is_microsoft and "bootmg" in name:
        return True
    return certs.binary_signer(path) in ("2011", "2023")


def status(esp_root: Path) -> EspStatus:
    bootmgr = winpath.resolve(esp_root, BOOTMGR)
    valid = False
    if bootmgr:
        info = pe.parse_file(bootmgr)
        valid = info.valid and info.machine == pe.MACHINE_AMD64 and info.size > 0
    fallback = winpath.resolve(esp_root, FALLBACK)
    fb_ms = bool(fallback) and is_microsoft_bootmgr(fallback)  # type: ignore[arg-type]
    others = []
    efi = winpath.resolve(esp_root, "EFI")
    if efi:
        others = sorted(p.name for p in winpath.listdir_ci(efi)
                        if p.is_dir() and p.name.lower() not in ("microsoft", "boot"))
    bcd = winpath.resolve(esp_root, BCD)
    return EspStatus(bootmgr, valid, bcd, fallback, fb_ms, others)


@dataclass
class CopyItem:
    src: Path
    dst_rel: str  # relative to the ESP root, canonical case


def _walk(src_dir: Path, dst_prefix: str, strip_ex: bool) -> list[CopyItem]:
    items = []
    for path in sorted(src_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_dir).as_posix()
        if strip_ex:
            rel = "/".join(_EX_RX.sub("", part) for part in rel.split("/"))
        items.append(CopyItem(path, f"{dst_prefix}/{rel}"))
    return items


def copy_plan(windows_dir: Path, boot_set: str = "EFI") -> list[CopyItem]:
    """Files bcdboot would copy from <Windows>\\Boot to the ESP."""
    boot = winpath.resolve(windows_dir, "Boot")
    if boot is None:
        raise FileNotFoundError("Windows\\Boot not found")
    efi = winpath.resolve(boot, "EFI")
    if efi is None:
        raise FileNotFoundError("Windows\\Boot\\EFI not found")
    items = {i.dst_rel.lower(): i for i in _walk(efi, MS_BOOT, False)}
    if boot_set == "EFI_EX":
        ex = winpath.resolve(boot, "EFI_EX")
        if ex is None:
            raise FileNotFoundError("Windows\\Boot\\EFI_EX not found")
        for i in _walk(ex, MS_BOOT, True):
            items[i.dst_rel.lower()] = i
    fonts = winpath.resolve(boot, "Fonts_EX" if boot_set == "EFI_EX" else "Fonts")
    fonts = fonts or winpath.resolve(boot, "Fonts")
    if fonts:
        for i in _walk(fonts, f"{MS_BOOT}/Fonts", boot_set == "EFI_EX"):
            items[i.dst_rel.lower()] = i
    resources = winpath.resolve(boot, "Resources")
    if resources:
        for i in _walk(resources, f"{MS_BOOT}/Resources", False):
            items[i.dst_rel.lower()] = i
    if f"{BOOTMGR}".lower() not in items:
        raise FileNotFoundError("bootmgfw.efi not found in Windows\\Boot\\EFI")
    return list(items.values())


def plan_size(items: list[CopyItem]) -> int:
    return sum(i.src.stat().st_size for i in items)


def fallback_allowed(st: EspStatus) -> bool:
    """Write EFI/Boot/bootx64.efi only if absent or already Microsoft's."""
    return st.fallback is None or st.fallback_is_microsoft


def apply_copy(esp_root: Path, items: list[CopyItem], record) -> list[str]:
    """Copy *items*; ``record(relpath, existed)`` is called before each write."""
    guard.require_write("EFI system partition")
    written = []
    for item in items:
        dst = winpath.resolve_or_build(esp_root, item.dst_rel)
        existed = dst.exists()
        record(item.dst_rel, existed)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(item.src, dst)
        written.append(item.dst_rel)
    return written
