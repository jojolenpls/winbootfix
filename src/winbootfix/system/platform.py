"""Host platform checks: root, UEFI, architecture, Secure Boot, live system."""

from __future__ import annotations

import os
import platform as _platform
from pathlib import Path

EFI_DIR = Path("/sys/firmware/efi")
EFIVARS = Path("/sys/firmware/efi/efivars")
GLOBAL_GUID = "8be4df61-93ca-11d2-aa0d-00e098032b8c"
IMAGE_SECURITY_GUID = "d719b2cb-3d3a-4596-a3bc-dad00e67656f"  # db / dbx


def is_root() -> bool:
    return os.geteuid() == 0


def is_uefi() -> bool:
    return EFI_DIR.is_dir()


def host_arch() -> str:
    return _platform.machine()


def efi_bitness() -> int | None:
    try:
        return int((EFI_DIR / "fw_platform_size").read_text().strip())
    except (OSError, ValueError):
        return None


def read_efivar(name: str, guid: str) -> bytes | None:
    """Return the variable payload (without the 4-byte attribute header)."""
    path = EFIVARS / f"{name}-{guid}"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data[4:] if len(data) >= 4 else None


def secure_boot_state() -> str:
    """'enabled', 'disabled', 'setup' or 'unknown'."""
    sb = read_efivar("SecureBoot", GLOBAL_GUID)
    setup = read_efivar("SetupMode", GLOBAL_GUID)
    if setup and setup[0] == 1:
        return "setup"
    if sb is None:
        return "unknown"
    return "enabled" if sb and sb[0] == 1 else "disabled"


def is_live_system() -> bool:
    try:
        cmdline = Path("/proc/cmdline").read_text()
    except OSError:
        cmdline = ""
    return "boot=live" in cmdline.split() or Path("/run/live/medium").is_dir()


def kernel_cmdline_param(name: str) -> str | None:
    try:
        for token in Path("/proc/cmdline").read_text().split():
            if token == name:
                return ""
            if token.startswith(name + "="):
                return token.split("=", 1)[1]
    except OSError:
        pass
    return None
