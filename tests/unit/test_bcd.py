import uuid

import pytest

from tests.conftest import needs_hivex
from tests.helpers.fakewin import REG_DWORD, dword, fill_hive
from tests.helpers.mkhive import make_hive
from winbootfix.boot.bcd import builder, device, validate
from winbootfix.boot.bcd import constants as C
from winbootfix.core import guard

ESP = ("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "99999999-8888-7777-6666-555555555555")
WIN = ("11111111-2222-3333-4444-555555555555", "99999999-8888-7777-6666-555555555555")


def test_device_roundtrip():
    blob = device.encode_gpt_partition(*WIN)
    assert len(blob) == 0x58
    assert blob[0x10] == 6 and blob[0x18] == 0x48
    assert blob[0x20:0x30] == uuid.UUID(WIN[0]).bytes_le
    info = device.decode(blob)
    assert info.is_gpt_partition and info.partition_guid == WIN[0] and info.disk_guid == WIN[1]


def test_device_mbr():
    info = device.decode(device.encode_mbr_partition(1048576, 0xDEADBEEF))
    assert info.style == device.STYLE_MBR and info.mbr_offset == 1048576 and info.mbr_signature == 0xDEADBEEF


@needs_hivex
@pytest.mark.parametrize("prefilled", [False, True])
def test_build_and_validate(tmp_path, prefilled):
    template = tmp_path / "BCD-Template"
    if prefilled:
        fill_hive(template, [(rf"Objects\{C.GLOBALSETTINGS}\Description", "Type", REG_DWORD,
                              dword(C.TYPE_INHERIT_GLOBAL))])
    else:
        make_hive(template)
    out = tmp_path / "BCD"
    with guard.allow_writes():
        ids = builder.build(template, out, ESP, WIN, "fr-FR", "Windows 11")
    s = validate.read(out)
    assert s.readable and s.has_bootmgr
    assert s.default.lower() == ids["loader"].lower()
    assert s.default_type == C.TYPE_OSLOADER
    assert s.bootmgr_device.partition_guid == ESP[0]
    assert s.default_osdevice.partition_guid == WIN[0]
    assert s.default_path.endswith("winload.efi") and s.default_systemroot == r"\Windows"
    assert validate.check(s, ESP[0], [WIN[0]]) == []
    assert "osdevice_mismatch" in validate.check(s, ESP[0], ["00000000-0000-0000-0000-000000000000"])
    assert "bootmgr_device_mismatch" in validate.check(s, "00000000-0000-0000-0000-000000000001", [WIN[0]])


@needs_hivex
def test_build_requires_write_window(tmp_path):
    template = make_hive(tmp_path / "BCD-Template")
    with pytest.raises(guard.WriteNotAllowed):
        builder.build(template, tmp_path / "BCD", ESP, WIN)


def test_validate_unreadable(tmp_path):
    p = tmp_path / "BCD"
    p.write_bytes(b"garbage")
    assert validate.check(validate.read(p), None, []) == ["unreadable"]
