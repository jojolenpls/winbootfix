"""UEFI boot entries (efibootmgr)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from winbootfix.core import guard
from winbootfix.core.run import run

log = logging.getLogger(__name__)

WINDOWS_LABEL = "Windows Boot Manager"
WINDOWS_LOADER = r"\EFI\Microsoft\Boot\bootmgfw.efi"

_ENTRY_RX = re.compile(r"^Boot([0-9A-Fa-f]{4})(\*?)\s+(.*)$")
_HD_RX = re.compile(r"HD\((\d+),GPT,([0-9A-Fa-f-]{36})", re.I)
_HD_MBR_RX = re.compile(r"HD\((\d+),MBR,", re.I)
_FILE_RX = re.compile(r"File\(([^)]*)\)", re.I)
_PATH_RX = re.compile(r"\)/?(\\[^\s()]+)")
_DEVPATH_START = re.compile(r"\s(HD|PciRoot|VenHw|VenMedia|BBS|Fv|FvVol|MAC|UsbClass|Uri|Acpi|Pci)\(")


@dataclass
class BootEntry:
    num: str
    active: bool
    label: str
    devpath: str
    partnum: int | None = None
    partuuid: str | None = None
    loader: str | None = None

    @property
    def is_windows(self) -> bool:
        return bool(self.loader and self.loader.lower().endswith(r"\microsoft\boot\bootmgfw.efi"))

    def points_to(self, partuuid: str | None) -> bool:
        return bool(partuuid and self.partuuid and self.partuuid.lower() == partuuid.lower())


@dataclass
class BootState:
    current: str | None
    order: list[str]
    entries: list[BootEntry]
    raw: str

    def entry(self, num: str) -> BootEntry | None:
        return next((e for e in self.entries if e.num.upper() == num.upper()), None)

    def windows_entries(self) -> list[BootEntry]:
        return [e for e in self.entries if e.is_windows or e.label.strip() == WINDOWS_LABEL]


def _split_label(rest: str) -> tuple[str, str]:
    if "\t" in rest:
        label, dev = rest.split("\t", 1)
        return label.strip(), dev.strip()
    m = _DEVPATH_START.search(" " + rest)
    if m:
        idx = m.start()
        return rest[:idx].strip(), rest[idx:].strip()
    return rest.strip(), ""


def parse(text: str) -> BootState:
    current, order, entries = None, [], []
    for line in text.splitlines():
        line = line.rstrip()
        if line.startswith("BootCurrent:"):
            current = line.split(":", 1)[1].strip()
        elif line.startswith("BootOrder:"):
            order = [x.strip().upper() for x in line.split(":", 1)[1].split(",") if x.strip()]
        else:
            m = _ENTRY_RX.match(line)
            if not m:
                continue
            label, dev = _split_label(m.group(3))
            entry = BootEntry(m.group(1).upper(), m.group(2) == "*", label, dev)
            hd = _HD_RX.search(dev)
            if hd:
                entry.partnum, entry.partuuid = int(hd.group(1)), hd.group(2).lower()
            elif _HD_MBR_RX.search(dev):
                entry.partnum = int(_HD_MBR_RX.search(dev).group(1))  # type: ignore[union-attr]
            f = _FILE_RX.search(dev) or _PATH_RX.search(dev)
            if f:
                entry.loader = f.group(1).replace("/", "\\")
            entries.append(entry)
    return BootState(current, order, entries, text)


def read_state() -> BootState:
    return parse(run(["efibootmgr", "-v"]).stdout)


def create_entry(disk: str, partnum: int, label: str = WINDOWS_LABEL, loader: str = WINDOWS_LOADER) -> str:
    """Create an entry and return its number. efibootmgr puts it first in BootOrder."""
    guard.require_write("UEFI NVRAM (new boot entry)")
    before = {e.num for e in read_state().entries}
    run(["efibootmgr", "-q", "-c", "-d", disk, "-p", str(partnum), "-L", label, "-l", loader])
    after = read_state()
    new = [e.num for e in after.entries if e.num not in before]
    if not new:
        raise RuntimeError("efibootmgr did not create a new entry")
    return new[0]


def set_order(order: list[str]) -> None:
    guard.require_write("UEFI NVRAM (BootOrder)")
    run(["efibootmgr", "-q", "-o", ",".join(order)])


def delete_entry(num: str) -> None:
    guard.require_write("UEFI NVRAM (delete entry)")
    run(["efibootmgr", "-q", "-b", num, "-B"])


def desired_order(order_before: list[str], new_num: str, state: BootState, windows_first: bool) -> list[str]:
    """Windows first, unless another OS loader was first and windows_first is False."""
    rest = [n for n in order_before if n != new_num]
    if windows_first or not rest:
        return [new_num] + rest
    first = state.entry(rest[0])
    if first and first.loader and not first.is_windows:
        return [rest[0], new_num] + rest[1:]
    return [new_num] + rest


def other_os_first(state: BootState) -> BootEntry | None:
    """The first BootOrder entry if it is a non-Windows OS loader on a disk (GRUB, systemd-boot...)."""
    if not state.order:
        return None
    first = state.entry(state.order[0])
    if first and first.loader and first.partuuid and not first.is_windows:
        return first
    return None
