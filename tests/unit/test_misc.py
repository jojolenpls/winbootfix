import json

import pytest

from tests.conftest import needs_hivex
from tests.helpers.fakewin import build_esp, build_windows
from tests.helpers.mkpe import build_pe, ms_pe
from winbootfix.boot import certs, efifiles
from winbootfix.core import guard
from winbootfix.core.quarantine import Quarantine
from winbootfix.core.report import anonymize
from winbootfix.system import winpath


def test_winpath_case_insensitive(tmp_path):
    (tmp_path / "WINDOWS/system32").mkdir(parents=True)
    (tmp_path / "WINDOWS/system32/Config").mkdir()
    assert winpath.resolve(tmp_path, "Windows/System32/config") == tmp_path / "WINDOWS/system32/Config"
    assert winpath.resolve(tmp_path, "Windows\\nope") is None
    assert winpath.resolve_or_build(tmp_path, "windows/new/x") == tmp_path / "WINDOWS/new/x"


@needs_hivex
def test_copy_plan_and_fallback_policy(tmp_path):
    win = build_windows(tmp_path / "win")
    items = efifiles.copy_plan(win)
    dsts = {i.dst_rel for i in items}
    assert "EFI/Microsoft/Boot/bootmgfw.efi" in dsts and "EFI/Microsoft/Boot/fr-FR/bootmgfw.efi.mui" in dsts
    assert "EFI/Microsoft/Boot/Resources/bootres.dll" in dsts
    esp = tmp_path / "esp"
    build_esp(esp, bootmgr=False, other_os=True)
    st = efifiles.status(esp)
    assert st.bootmgr is None and st.other_loaders == ["debian"] and not efifiles.fallback_allowed(st)
    (esp / "EFI/Boot/bootx64.efi").write_bytes(ms_pe("bootmgfw.efi"))
    assert efifiles.fallback_allowed(efifiles.status(esp))
    with pytest.raises(guard.WriteNotAllowed):
        efifiles.apply_copy(esp, items, lambda *a: None)


def test_choose_boot_set(tmp_path):
    boot = tmp_path / "Boot"
    (boot / "EFI").mkdir(parents=True)
    fw_default = certs.FirmwareCerts(True, True, False, False)
    assert certs.choose_boot_set(boot, fw_default, None, "enabled") == ("EFI", "no_ex")
    revoked = certs.FirmwareCerts(True, True, True, True)
    assert certs.choose_boot_set(boot, revoked, None, "enabled")[1] == "no_ex_but_2011_revoked"
    (boot / "EFI_EX").mkdir()
    assert certs.choose_boot_set(boot, fw_default, None, "enabled") == ("EFI", "default_2011")
    assert certs.choose_boot_set(boot, fw_default, "2023", "enabled") == ("EFI_EX", "existing_2023")
    assert certs.choose_boot_set(boot, revoked, None, "enabled") == ("EFI_EX", "2011_revoked")


def test_binary_signer(tmp_path):
    p = tmp_path / "b.efi"
    p.write_bytes(build_pe(security=b"Windows UEFI CA 2023"))
    assert certs.binary_signer(p) == "2023"
    p.write_bytes(build_pe(security=b"Microsoft Windows Production PCA 2011"))
    assert certs.binary_signer(p) == "2011"


def test_quarantine_moves_and_writes_restore_files(tmp_path):
    root = tmp_path / "vol"
    f = root / "Windows/System32/wintab32.dll"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"MZ data")
    q = Quarantine(root, "20240101-000000")
    with pytest.raises(guard.WriteNotAllowed):
        q.move(f, "wrong_arch")
    with guard.allow_writes():
        e = q.move(f, "wrong_arch", ["Wacom tablet driver"])
    assert not f.exists() and (q.dir / e.stored).read_bytes() == b"MZ data"
    data = json.loads((q.dir / "restore.json").read_text())
    assert data["files"][0]["original"] == "Windows\\System32\\wintab32.dll"
    assert "%SystemDrive%\\Windows\\System32\\wintab32.dll" in (q.dir / "restore.cmd").read_text()
    assert (q.dir / "restore.cmd").read_bytes().count(b"\r\n") >= 3


def test_anonymize():
    text = anonymize(r"C:\Users\Marie\x /home/paul/y 123456-123456-123456-123456-123456-123456-123456-123456 aa:bb:cc:dd:ee:ff")
    assert "Marie" not in text and "paul" not in text and "<bitlocker-key>" in text and "<mac>" in text


def test_bitlocker_key_check():
    from winbootfix.system import bitlocker
    good = "-".join(["000011"] * 8)
    assert bitlocker.normalize_key(good.replace("-", " ")) == good
    with pytest.raises(bitlocker.BitLockerError):
        bitlocker.normalize_key("123")
    with pytest.raises(bitlocker.BitLockerError):
        bitlocker.normalize_key("-".join(["000012"] * 8))


def test_hardware_pci(tmp_path):
    from winbootfix.system import hardware
    for slot, vendor, device, cls in (("0000:00:02.0", "0x8086", "0x9a49", "0x030000"),
                                      ("0000:00:0e.0", "0x8086", "0x9a0b", "0x010400"),
                                      ("0000:01:00.0", "0x10de", "0x2484", "0x030000")):
        d = tmp_path / slot
        d.mkdir()
        (d / "vendor").write_text(vendor)
        (d / "device").write_text(device)
        (d / "class").write_text(cls)
    devs = hardware.pci_devices(tmp_path)
    assert [g.vendor_name for g in hardware.gpus(devs)] == ["Intel", "NVIDIA"]
    hidden = hardware.hidden_storage_controllers(devs)
    assert len(hidden) == 1 and hidden[0].is_vmd
    assert hardware.vendor_key({"sys_vendor": "Micro-Star International Co., Ltd."}) == "msi"
    assert hardware.vendor_key({"sys_vendor": "ASUSTeK COMPUTER INC."}) == "asus"
    assert hardware.vendor_key({"sys_vendor": "Unknown"}) == "generic"


def test_cbs_scan(tmp_path):
    from winbootfix.health.integrity import scan_cbs
    log = tmp_path / "CBS.log"
    log.write_text(
        "2024-01-01, Info CSI 0001 [SR] Verify complete\n"
        "2024-01-01, Info CSI 0002 [SR] Cannot repair member file [l:10]'d3d11.dll' of Microsoft-Windows-Direct3D\n"
        "2024-01-01, Info CSI 0003 Hashes for file member [l:9]'dxgi.dll' do not match\n")
    count, files = scan_cbs(log)
    assert count == 2 and files == ["d3d11.dll", "dxgi.dll"]
