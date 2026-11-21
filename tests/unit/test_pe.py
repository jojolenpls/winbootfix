from tests.helpers.mkpe import MACHINE_AMD64, MACHINE_I386, build_pe, ms_pe
from winbootfix.windows import pe


def _parse(tmp_path, data, name="x.dll", version=True):
    p = tmp_path / name
    p.write_bytes(data)
    return pe.parse_file(p, with_version=version)


def test_x64_with_version(tmp_path):
    info = _parse(tmp_path, ms_pe("kernel32.dll"))
    assert info.valid and info.arch == "x64" and info.is_dll
    assert info.is_microsoft
    assert info.version["OriginalFilename"] == "kernel32.dll"


def test_x86_third_party(tmp_path):
    info = _parse(tmp_path, build_pe(MACHINE_I386, version={"CompanyName": "Wacom Technology Corp."}))
    assert info.machine == MACHINE_I386 and not info.is_microsoft
    assert info.company.startswith("Wacom")


def test_dotnet_anycpu_and_32bit(tmp_path):
    assert _parse(tmp_path, build_pe(MACHINE_I386, clr_flags=0x1)).is_anycpu
    assert not _parse(tmp_path, build_pe(MACHINE_I386, clr_flags=0x3), "b.dll").is_anycpu


def test_resource_only(tmp_path):
    assert _parse(tmp_path, build_pe(MACHINE_I386, entry_point=0, imports=False)).is_resource_only
    assert not _parse(tmp_path, build_pe(MACHINE_AMD64), "b.dll").is_resource_only


def test_empty_and_garbage(tmp_path):
    assert _parse(tmp_path, b"").error == "empty file"
    bad = _parse(tmp_path, b"MZ" + b"\0" * 100, "b.dll")
    assert not bad.valid
    assert not _parse(tmp_path, b"hello world" * 10, "c.dll").valid


def test_security_blob(tmp_path):
    p = tmp_path / "s.efi"
    p.write_bytes(build_pe(security=b"--Windows UEFI CA 2023--"))
    assert b"Windows UEFI CA 2023" in pe.security_blob(p)
    p.write_bytes(build_pe())
    assert pe.security_blob(p) == b""
