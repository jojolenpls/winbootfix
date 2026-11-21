import struct

import pytest

from tests.conftest import needs_hivex
from tests.helpers.fakewin import REG_DWORD, REG_SZ, dword, fill_hive, sz
from winbootfix.core import guard
from winbootfix.windows import hive as hv


@needs_hivex
def test_read_write(tmp_path):
    p = fill_hive(tmp_path / "SYSTEM", [("Select", "Current", REG_DWORD, dword(2)),
                                        (r"ControlSet002\Services\x", "ImagePath", REG_SZ, sz(r"\SystemRoot\x.sys"))])
    with hv.Hive(p) as h:
        assert h.value("select", "current") == 2
        assert hv.current_control_set(h) == "ControlSet002"
        assert h.value(r"ControlSet002\Services\X", "ImagePath") == r"\SystemRoot\x.sys"
        assert h.subkeys(r"ControlSet002\Services") == ["x"]
        assert h.value("Nope", "x", 7) == 7
    with pytest.raises(guard.WriteNotAllowed):
        hv.Hive(p, write=True)
    with guard.allow_writes():
        with hv.Hive(p, write=True) as h:
            h.set_dword(r"ControlSet002\Services\x", "Start", 3)
            h.set_sz(r"New\Key", "Name", "value")
            assert h.delete_value(r"ControlSet002\Services\x", "ImagePath")
            h.commit()
    with hv.Hive(p) as h:
        assert h.values(r"ControlSet002\Services\x") == {"Start": 3}
        assert h.value(r"New\Key", "Name") == "value"


@needs_hivex
def test_dirty_hive_is_not_written(tmp_path):
    p = fill_hive(tmp_path / "SOFTWARE", [("A", "B", REG_DWORD, dword(1))])
    data = bytearray(p.read_bytes())
    struct.pack_into("<I", data, 4, 5)  # primary sequence != secondary
    p.write_bytes(bytes(data))
    assert hv.header_info(p).dirty
    with guard.allow_writes(), pytest.raises(hv.HiveError):
        hv.Hive(p, write=True)


def test_invalid_hive(tmp_path):
    p = tmp_path / "bad"
    p.write_bytes(b"nope")
    assert not hv.header_info(p).valid
    with pytest.raises(hv.HiveError):
        hv.Hive(p)


def test_decode_values():
    assert hv.decode_value(hv.REG_MULTI_SZ, hv.encode_multi_sz(["a", "bc"])) == ["a", "bc"]
    assert hv.decode_value(hv.REG_SZ, hv.encode_sz("é")) == "é"
    assert hv.decode_value(hv.REG_QWORD, struct.pack("<Q", 2 ** 40)) == 2 ** 40
