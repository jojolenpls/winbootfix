"""Build fake Windows installations and EFI partitions (plain directories) for tests."""

from __future__ import annotations

import struct
import uuid
from pathlib import Path

from tests.helpers.mkhive import make_hive
from tests.helpers.mkpe import MACHINE_AMD64, MACHINE_I386, build_pe, ms_pe

DISPLAY = "{4d36e968-e325-11ce-bfc1-08002be10318}"
NV_HW = "VEN_10DE&DEV_2484&SUBSYS_146B10DE&REV_A1"
NV_PKG = "nv_dispi.inf_amd64_0123456789abcdef"

REG_SZ, REG_BINARY, REG_DWORD, REG_MULTI_SZ = 1, 3, 4, 7


def sz(text: str) -> bytes:
    return (text + "\0").encode("utf-16-le")


def dword(v: int) -> bytes:
    return struct.pack("<I", v)


def fill_hive(path: Path, values: list[tuple[str, str, int, bytes]], keys: list[str] = ()) -> Path:
    """values: (key path, value name, type, data)."""
    import hivex

    make_hive(path)
    h = hivex.Hivex(str(path), write=True)

    def ensure(kp: str):
        node = h.root()
        for part in [p for p in kp.split("\\") if p]:
            child = h.node_get_child(node, part)
            node = child if child else h.node_add_child(node, part)
        return node

    for k in keys:
        ensure(k)
    for kp, name, vtype, data in values:
        h.node_set_value(ensure(kp), {"key": name, "t": vtype, "value": data})
    h.commit(None)
    return path


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def build_windows(root: Path, *, partuuid: str = "11111111-2222-3333-4444-555555555555", lcid: str = "040C",
                  build: str = "19045", gpu_start: int = 3, gpu_sys: bool = True, driverstore: bool = True,
                  bad_dlls: bool = False, pending: bool = False, cbs_corrupt: bool = False,
                  missing: tuple[str, ...] = (), boot_ex: bool = False, product: str = "Windows 10 Pro") -> Path:
    win = root / "Windows"
    sys32 = win / "System32"
    import json
    crit = json.loads((Path(__file__).resolve().parents[2] / "src/winbootfix/data/critical_files.json").read_text())
    for rel in crit["files"]:
        if rel.startswith("System32/config/") or rel in missing:
            continue
        name = rel.split("/")[-1]
        machine = MACHINE_I386 if rel.startswith("SysWOW64/") else MACHINE_AMD64
        write(win / rel, ms_pe(name, machine))
    # boot files
    write(win / "Boot/EFI/bootmgfw.efi", ms_pe("bootmgfw.efi", security=b"..Microsoft Windows Production PCA 2011.."))
    write(win / "Boot/EFI/bootmgr.efi", ms_pe("bootmgr.efi"))
    write(win / "Boot/EFI/memtest.efi", ms_pe("memtest.efi"))
    write(win / "Boot/EFI/en-US/bootmgfw.efi.mui", b"mui")
    write(win / "Boot/EFI/fr-FR/bootmgfw.efi.mui", b"mui")
    write(win / "Boot/Fonts/wgl4_boot.ttf", b"font")
    write(win / "Boot/Resources/bootres.dll", ms_pe("bootres.dll"))
    if boot_ex:
        write(win / "Boot/EFI_EX/bootmgfw_EX.efi", ms_pe("bootmgfw.efi", security=b"..Windows UEFI CA 2023.."))
        write(win / "Boot/EFI_EX/en-US/bootmgfw_EX.efi.mui", b"mui-ex")
        write(win / "Boot/Fonts_EX/wgl4_boot_EX.ttf", b"font-ex")
    # graphics driver package
    if driverstore:
        write(sys32 / "DriverStore/FileRepository" / NV_PKG / "nv_dispi.inf", b"; inf")
        if gpu_sys:
            write(sys32 / "DriverStore/FileRepository" / NV_PKG / "nvlddmkm.sys", ms_pe("nvlddmkm.sys", dll=False))
    if bad_dlls:
        write(sys32 / "wintab32.dll", build_pe(MACHINE_I386, version={"CompanyName": "Wacom Technology Corp."}))
        write(sys32 / "msvcp140.dll", build_pe(MACHINE_I386, version={"CompanyName": "Microsoft Corporation"}))
        write(sys32 / "empty.dll", b"")
        write(win / "SysWOW64/foo64.dll", build_pe(MACHINE_AMD64, version={"CompanyName": "Foo Ltd"}))
        write(sys32 / "anycpu.dll", build_pe(MACHINE_I386, clr_flags=1))
        write(sys32 / "resonly.dll", build_pe(MACHINE_I386, entry_point=0, imports=False))
    if pending:
        write(win / "WinSxS/pending.xml", b"<pending/>")
    log = "2024-01-01 10:00:00, Info CSI 00000001 [SR] Verify complete\n"
    if cbs_corrupt:
        log += "2024-01-01 10:00:01, Info CSI 00000002 [SR] Cannot repair member file [l:10]'d3d11.dll' of Microsoft-Windows-Direct3D\n"
    write(win / "Logs/CBS/CBS.log", log.encode())

    cfg = sys32 / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    ccs = "ControlSet001"
    img = rf"\SystemRoot\System32\DriverStore\FileRepository\{NV_PKG}\nvlddmkm.sys"
    fill_hive(cfg / "SYSTEM", [
        ("Select", "Current", REG_DWORD, dword(1)),
        (rf"{ccs}\Control\Nls\Language", "InstallLanguage", REG_SZ, sz(lcid)),
        (rf"{ccs}\Control\Windows", "ShutdownTime", REG_BINARY, struct.pack("<Q", 133500000000000000)),
        (rf"{ccs}\Services\nvlddmkm", "Start", REG_DWORD, dword(gpu_start)),
        (rf"{ccs}\Services\nvlddmkm", "ImagePath", 2, sz(img)),
        (rf"{ccs}\Services\BasicDisplay", "Start", REG_DWORD, dword(1)),
        (rf"{ccs}\Enum\PCI\{NV_HW}\4&1a2b3c&0&0008", "ClassGUID", REG_SZ, sz(DISPLAY)),
        (rf"{ccs}\Enum\PCI\{NV_HW}\4&1a2b3c&0&0008", "Service", REG_SZ, sz("nvlddmkm")),
        (rf"{ccs}\Enum\PCI\{NV_HW}\4&1a2b3c&0&0008", "Driver", REG_SZ, sz(DISPLAY + "\\0000")),
        (rf"{ccs}\Enum\PCI\{NV_HW}\4&1a2b3c&0&0008", "DeviceDesc", REG_SZ, sz("@oem5.inf,%nvidia%;NVIDIA GeForce RTX 3070")),
        (rf"{ccs}\Control\Class\{DISPLAY}\0000", "DriverDesc", REG_SZ, sz("NVIDIA GeForce RTX 3070")),
        (rf"{ccs}\Control\Class\{DISPLAY}\0000", "DriverVersion", REG_SZ, sz("31.0.15.5222")),
        (rf"{ccs}\Control\Class\{DISPLAY}\0000", "InfPath", REG_SZ, sz("oem5.inf")),
        (rf"{ccs}\Control\Class\{DISPLAY}\0000", "ProviderName", REG_SZ, sz("NVIDIA")),
        ("MountedDevices", "\\DosDevices\\C:", REG_BINARY, b"DMIO:ID:" + uuid.UUID(partuuid).bytes_le),
    ], keys=[rf"{ccs}\Control\MUI\UILanguages\fr-FR"])
    fill_hive(cfg / "SOFTWARE", [
        (r"Microsoft\Windows NT\CurrentVersion", "ProductName", REG_SZ, sz(product)),
        (r"Microsoft\Windows NT\CurrentVersion", "EditionID", REG_SZ, sz("Professional")),
        (r"Microsoft\Windows NT\CurrentVersion", "DisplayVersion", REG_SZ, sz("22H2")),
        (r"Microsoft\Windows NT\CurrentVersion", "CurrentBuild", REG_SZ, sz(build)),
        (r"Microsoft\Windows NT\CurrentVersion", "UBR", REG_DWORD, dword(4170)),
    ], keys=[r"Microsoft\Windows\CurrentVersion\RunOnce"])
    fill_hive(cfg / "DRIVERS", [
        (r"DriverDatabase\DriverInfFiles\oem5.inf", "Active", REG_SZ, sz(NV_PKG)),
        (r"DriverDatabase\DriverInfFiles\oem5.inf", "", REG_MULTI_SZ, (NV_PKG + "\0\0").encode("utf-16-le")),
    ])
    fill_hive(cfg / "DEFAULT", [(r"Keyboard Layout\Preload", "1", REG_SZ, sz("0000040c"))])
    for name in ("SAM", "SECURITY"):
        make_hive(cfg / name)
    make_hive(cfg / "BCD-Template")
    return win


def build_esp(root: Path, *, bootmgr: bool = True, other_os: bool = False, bcd: Path | None = None) -> Path:
    efi = root / "EFI"
    efi.mkdir(parents=True, exist_ok=True)
    if bootmgr:
        write(efi / "Microsoft/Boot/bootmgfw.efi", ms_pe("bootmgfw.efi", security=b"..Microsoft Windows Production PCA 2011.."))
    if bcd is not None:
        write(efi / "Microsoft/Boot/BCD", bcd.read_bytes())
    if other_os:
        shim = build_pe(MACHINE_AMD64, dll=False)
        write(efi / "debian/shimx64.efi", shim)
        write(efi / "debian/grubx64.efi", shim)
        write(efi / "Boot/bootx64.efi", shim)
    return efi
