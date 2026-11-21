"""Secure Boot certificates: choose between the 2011 and 2023 signed Windows boot files.

Microsoft signs boot managers with "Microsoft Windows Production PCA 2011"
(files in Windows\\Boot\\EFI) and, since the BlackLotus mitigations, with
"Windows UEFI CA 2023" (files in Windows\\Boot\\EFI_EX, *_EX names). If the
firmware revoked the 2011 CA (DBX), only 2023 files boot with Secure Boot on.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from winbootfix.system import platform
from winbootfix.windows import pe

CA_2011 = b"Microsoft Windows Production PCA 2011"
CA_2023 = b"Windows UEFI CA 2023"


@dataclass
class FirmwareCerts:
    readable: bool
    db_has_2011: bool = False
    db_has_2023: bool = False
    dbx_revokes_2011: bool = False


def firmware_certs() -> FirmwareCerts:
    db = platform.read_efivar("db", platform.IMAGE_SECURITY_GUID)
    dbx = platform.read_efivar("dbx", platform.IMAGE_SECURITY_GUID)
    if db is None:
        return FirmwareCerts(False)
    return FirmwareCerts(True, CA_2011 in db, CA_2023 in db, bool(dbx) and CA_2011 in dbx)


def binary_signer(path: Path) -> str:
    """'2023', '2011' or 'unknown' from the embedded Authenticode chain."""
    blob = pe.security_blob(path)
    if CA_2023 in blob:
        return "2023"
    if CA_2011 in blob:
        return "2011"
    return "unknown"


def choose_boot_set(windows_boot_dir: Path, fw: FirmwareCerts, existing_signer: str | None,
                    secure_boot: str) -> tuple[str, str]:
    """Return (set, reason) where set is 'EFI' or 'EFI_EX'."""
    from winbootfix.system import winpath

    has_ex = winpath.resolve(windows_boot_dir, "EFI_EX") is not None
    if not has_ex:
        if fw.dbx_revokes_2011 and secure_boot == "enabled":
            return "EFI", "no_ex_but_2011_revoked"
        return "EFI", "no_ex"
    if existing_signer == "2023":
        return "EFI_EX", "existing_2023"
    if fw.dbx_revokes_2011:
        return "EFI_EX", "2011_revoked"
    if fw.readable and fw.db_has_2023 and not fw.db_has_2011:
        return "EFI_EX", "db_only_2023"
    return "EFI", "default_2011"
