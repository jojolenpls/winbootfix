"""Windows installation discovery (version, edition, architecture, language)."""

from __future__ import annotations

import json
import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from winbootfix import paths
from winbootfix.system import winpath
from winbootfix.system.disks import Partition
from winbootfix.windows import pe
from winbootfix.windows.hive import Hive, HiveError, current_control_set

log = logging.getLogger(__name__)


@dataclass
class WindowsInstall:
    partition: Partition
    root: Path                       # mount point of the volume
    device: str                      # block device or decrypted image actually mounted
    windows_dir: Path
    product_name: str = "Windows"
    edition_id: str = ""
    display_version: str = ""
    build: int = 0
    ubr: int = 0
    arch: str = "unknown"
    language: str | None = None      # BCP-47, e.g. fr-FR
    keyboard_lcid: str | None = None  # e.g. 0000040c
    last_shutdown: datetime | None = None
    system_letter: str | None = None
    bitlocker: bool = False
    hibernated: bool = False
    dirty: bool | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_win11(self) -> bool:
        return self.build >= 22000

    @property
    def label(self) -> str:
        name = self.product_name
        if self.is_win11:
            name = name.replace("Windows 10", "Windows 11")
        ver = f" {self.display_version}" if self.display_version else ""
        return f"{name}{ver} (build {self.build}.{self.ubr})" if self.build else name

    def path(self, rel: str) -> Path | None:
        return winpath.resolve(self.root, rel)

    def config(self, hive: str) -> Path | None:
        return winpath.resolve(self.windows_dir, f"System32/config/{hive}")


def filetime_to_datetime(ft: int) -> datetime | None:
    if not ft:
        return None
    try:
        return datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ft // 10)
    except OverflowError:
        return None


def lcid_to_tag(lcid: str) -> str | None:
    table = json.loads(paths.data_file("languages.json").read_text(encoding="utf-8"))
    return table.get("lcid", {}).get(lcid.lower()[-4:])


def find_windows_dir(root: Path) -> Path | None:
    win = winpath.resolve(root, "Windows")
    if win and winpath.resolve(win, "System32/config/SYSTEM"):
        return win
    return None


def read_install(partition: Partition, root: Path, device: str) -> WindowsInstall | None:
    windows_dir = find_windows_dir(root)
    if windows_dir is None:
        return None
    inst = WindowsInstall(partition=partition, root=root, device=device, windows_dir=windows_dir)
    kernel = winpath.resolve(windows_dir, "System32/ntoskrnl.exe")
    if kernel:
        inst.arch = pe.parse_file(kernel).arch
    software = inst.config("SOFTWARE")
    if software:
        try:
            with Hive(software) as h:
                v = h.values(r"Microsoft\Windows NT\CurrentVersion")
                inst.product_name = v.get("ProductName") or inst.product_name
                inst.edition_id = v.get("EditionID") or ""
                inst.display_version = v.get("DisplayVersion") or v.get("ReleaseId") or ""
                try:
                    inst.build = int(v.get("CurrentBuild") or v.get("CurrentBuildNumber") or 0)
                except ValueError:
                    inst.build = 0
                ubr = v.get("UBR")
                inst.ubr = ubr if isinstance(ubr, int) else 0
        except HiveError as exc:
            inst.notes.append(f"SOFTWARE hive: {exc}")
    system = inst.config("SYSTEM")
    if system:
        try:
            with Hive(system) as h:
                ccs = current_control_set(h)
                langs = h.subkeys(rf"{ccs}\Control\MUI\UILanguages")
                install_lcid = h.value(rf"{ccs}\Control\Nls\Language", "InstallLanguage")
                if isinstance(install_lcid, str):
                    inst.language = lcid_to_tag(install_lcid)
                if not inst.language and langs:
                    inst.language = langs[0]
                raw = h.raw_value(rf"{ccs}\Control\Windows", "ShutdownTime")
                if raw and len(raw[1]) >= 8:
                    inst.last_shutdown = filetime_to_datetime(struct.unpack_from("<Q", raw[1])[0])
                inst.system_letter = system_drive_letter(h, partition.partuuid)
        except HiveError as exc:
            inst.notes.append(f"SYSTEM hive: {exc}")
    default = inst.config("DEFAULT")
    if default:
        try:
            with Hive(default) as h:
                kb = h.value(r"Keyboard Layout\Preload", "1")
                if isinstance(kb, str):
                    inst.keyboard_lcid = kb
        except HiveError:
            pass
    return inst


def system_drive_letter(system_hive: Hive, partuuid: str | None) -> str | None:
    """Drive letter Windows gives to this partition (SYSTEM\\MountedDevices)."""
    if not partuuid:
        return None
    import uuid as _uuid
    try:
        want = b"DMIO:ID:" + _uuid.UUID(partuuid).bytes_le
    except ValueError:
        return None
    node_values = system_hive.values("MountedDevices")
    for name, data in node_values.items():
        if name.startswith("\\DosDevices\\") and isinstance(data, bytes) and data == want:
            return name[-2:]
    return None
