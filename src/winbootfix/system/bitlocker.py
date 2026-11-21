"""Optional BitLocker support through dislocker (recovery key only)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from winbootfix.core.run import CommandError, run, which

log = logging.getLogger(__name__)

BASE = Path("/run/winbootfix/dislocker")
RECOVERY_KEY_RX = re.compile(r"^\d{6}(-\d{6}){7}$")


class BitLockerError(RuntimeError):
    pass


def available() -> bool:
    return which("dislocker") is not None or which("dislocker-fuse") is not None


def normalize_key(key: str) -> str:
    digits = re.sub(r"\D", "", key)
    if len(digits) != 48:
        raise BitLockerError("a BitLocker recovery key has 48 digits (8 groups of 6)")
    groups = [digits[i:i + 6] for i in range(0, 48, 6)]
    for g in groups:
        if int(g) % 11 != 0:  # every block of a valid recovery key is divisible by 11
            raise BitLockerError("this does not look like a valid BitLocker recovery key")
    return "-".join(groups)


def unlock(device: str, recovery_key: str, rw: bool = False) -> Path:
    """Decrypt *device* with dislocker; returns the path of the decrypted NTFS image file."""
    key = normalize_key(recovery_key)
    binary = which("dislocker") or which("dislocker-fuse")
    if not binary:
        raise BitLockerError("dislocker is not installed")
    target = BASE / Path(device).name
    target.mkdir(parents=True, exist_ok=True)
    try:
        args = [binary] + ([] if rw else ["-r"]) + ["-V", device, f"-p{key}", "--", str(target)]
        run(args, secret=True)
    except CommandError as exc:
        raise BitLockerError("dislocker could not unlock the volume (wrong key?)") from exc
    image = target / "dislocker-file"
    if not image.exists():
        raise BitLockerError("dislocker did not create the decrypted image")
    return image


def unlock_clearkey(device: str) -> Path | None:
    """Volumes with BitLocker "waiting for activation" or suspended store a clear key:
    they open without the recovery key (common with Windows 11 automatic device encryption)."""
    binary = which("dislocker") or which("dislocker-fuse")
    if not binary:
        return None
    target = BASE / Path(device).name
    target.mkdir(parents=True, exist_ok=True)
    try:
        run([binary, "-r", "-V", device, "--clearkey", "--", str(target)])
    except CommandError:
        return None
    image = target / "dislocker-file"
    return image if image.exists() else None


def lock(device: str) -> None:
    target = BASE / Path(device).name
    run(["umount", str(target)], check=False)
