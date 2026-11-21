import struct

from winbootfix.system import ntfs


def boot_sector(oem=b"NTFS    ", bps=512, spc=8, mft_lcn=4, cpr=-10):
    b = bytearray(512)
    b[3:11] = oem
    struct.pack_into("<H", b, 0x0B, bps)
    b[0x0D] = spc
    struct.pack_into("<Q", b, 0x30, mft_lcn)
    struct.pack_into("<b", b, 0x40, cpr)
    return bytes(b)


def volume_record(flags, size=1024, sector=512):
    rec = bytearray(size)
    rec[0:4] = b"FILE"
    usa_off, usa_count = 0x30, size // sector + 1
    struct.pack_into("<HH", rec, 4, usa_off, usa_count)
    struct.pack_into("<H", rec, 0x14, 0x38)
    off = 0x38
    content = struct.pack("<QBBH", 0, 3, 1, flags)
    attr = bytearray(0x18 + len(content))
    struct.pack_into("<II", attr, 0, 0x70, len(attr) + (-len(attr) % 8))
    attr[8] = 0
    struct.pack_into("<IH", attr, 0x10, len(content), 0x18)
    attr[0x18:] = content
    attr += b"\0" * (-len(attr) % 8)
    rec[off:off + len(attr)] = attr
    struct.pack_into("<I", rec, off + len(attr), 0xFFFFFFFF)
    usn = b"\x07\x00"
    rec[usa_off:usa_off + 2] = usn
    for i in range(1, usa_count):
        end = i * sector - 2
        rec[usa_off + 2 * i:usa_off + 2 * i + 2] = rec[end:end + 2]
        rec[end:end + 2] = usn
    return bytes(rec)


def test_classify():
    assert ntfs.classify_boot_sector(boot_sector()) == "ntfs"
    assert ntfs.classify_boot_sector(boot_sector(b"-FVE-FS-")) == "bitlocker"
    assert ntfs.classify_boot_sector(b"\0" * 512) == "other"


def test_geometry():
    bps, cluster, mft_off, rec = ntfs.parse_geometry(boot_sector())
    assert (bps, cluster, mft_off, rec) == (512, 4096, 4 * 4096, 1024)


def test_dirty_flag_from_image(tmp_path):
    for flags, dirty in ((0x0001, True), (0x0000, False)):
        img = bytearray(64 * 1024)
        img[0:512] = boot_sector()
        mft = 4 * 4096
        img[mft + 3 * 1024: mft + 4 * 1024] = volume_record(flags)
        p = tmp_path / "vol.img"
        p.write_bytes(bytes(img))
        info = ntfs.inspect_volume(str(p))
        assert info.kind == "ntfs" and info.dirty is dirty and info.ntfs_version == "3.1"


def test_bitlocker_image(tmp_path):
    p = tmp_path / "bl.img"
    p.write_bytes(boot_sector(b"-FVE-FS-") + b"\0" * 4096)
    assert ntfs.inspect_volume(str(p)).kind == "bitlocker"


def test_hibernation_header():
    assert ntfs.is_hibernation_header(b"HIBR")
    assert ntfs.is_hibernation_header(b"wake")
    assert not ntfs.is_hibernation_header(b"\0\0\0\0")
