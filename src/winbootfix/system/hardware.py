"""Hardware facts read from sysfs (no dmidecode/lspci needed, works under kernel lockdown)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DMI = Path("/sys/class/dmi/id")
PCI = Path("/sys/bus/pci/devices")

PCI_VENDORS = {
    "10de": "NVIDIA", "1002": "AMD", "1022": "AMD", "8086": "Intel", "1414": "Microsoft Hyper-V",
    "1af4": "Red Hat (virtio)", "1234": "QEMU", "15ad": "VMware", "80ee": "VirtualBox",
    "1b36": "Red Hat (QEMU)", "5143": "Qualcomm", "14e4": "Broadcom", "1d17": "Zhaoxin",
}

# Intel Volume Management Device controllers (hide NVMe disks from OSes without the VMD driver).
INTEL_VMD_IDS = {"201d", "28c0", "467f", "4c3d", "7d0b", "9a0b", "a77f", "ad0b", "b06f", "b60b", "c43d"}

_VENDOR_KEYS = [
    ("asus", "asus"), ("micro-star", "msi"), ("msi", "msi"), ("gigabyte", "gigabyte"),
    ("asrock", "asrock"), ("dell", "dell"), ("alienware", "dell"), ("hewlett", "hp"), ("hp", "hp"),
    ("lenovo", "lenovo"), ("acer", "acer"), ("microsoft", "microsoft"), ("samsung", "samsung"),
    ("toshiba", "toshiba"), ("dynabook", "toshiba"), ("huawei", "huawei"), ("framework", "framework"),
    ("qemu", "virtual"), ("innotek", "virtual"), ("vmware", "virtual"),
]


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return ""


def dmi() -> dict[str, str]:
    keys = ("sys_vendor", "product_name", "product_version", "board_vendor", "board_name",
            "bios_vendor", "bios_version", "bios_date", "chassis_type")
    return {k: _read(DMI / k) for k in keys}


def vendor_key(info: dict[str, str] | None = None) -> str:
    """Normalised manufacturer used to pick BIOS menu hints (bios_hints.json)."""
    info = info if info is not None else dmi()
    for field in ("sys_vendor", "board_vendor"):
        val = info.get(field, "").lower()
        for needle, key in _VENDOR_KEYS:
            if needle in val:
                return key
    return "generic"


def is_laptop(info: dict[str, str] | None = None) -> bool:
    info = info if info is not None else dmi()
    try:
        return int(info.get("chassis_type") or 0) in (8, 9, 10, 14, 30, 31, 32)
    except ValueError:
        return False


@dataclass
class PciDevice:
    slot: str
    vendor: str
    device: str
    pci_class: str  # 6 hex digits, e.g. 030000
    driver: str | None

    @property
    def vendor_name(self) -> str:
        return PCI_VENDORS.get(self.vendor, self.vendor)

    @property
    def hwid(self) -> str:
        return f"VEN_{self.vendor.upper()}&DEV_{self.device.upper()}"

    @property
    def is_display(self) -> bool:
        return self.pci_class.startswith("03")

    @property
    def is_vmd(self) -> bool:
        return self.vendor == "8086" and self.device in INTEL_VMD_IDS

    @property
    def is_raid(self) -> bool:
        return self.pci_class.startswith("0104")

    @property
    def is_storage(self) -> bool:
        return self.pci_class.startswith("01")


def pci_devices(root: Path = PCI) -> list[PciDevice]:
    out = []
    if not root.is_dir():
        return out
    for dev in sorted(root.iterdir()):
        vendor = _read(dev / "vendor").lower().removeprefix("0x")
        device = _read(dev / "device").lower().removeprefix("0x")
        cls = _read(dev / "class").lower().removeprefix("0x").rjust(6, "0")
        drv = dev / "driver"
        driver = drv.resolve().name if drv.exists() else None
        out.append(PciDevice(dev.name, vendor, device, cls, driver))
    return out


def gpus(devices: list[PciDevice] | None = None) -> list[PciDevice]:
    return [d for d in (devices if devices is not None else pci_devices()) if d.is_display]


def hidden_storage_controllers(devices: list[PciDevice] | None = None) -> list[PciDevice]:
    """Controllers that typically hide disks: Intel VMD, RAID-mode SATA (RST)."""
    devices = devices if devices is not None else pci_devices()
    return [d for d in devices if d.is_vmd or d.is_raid]
