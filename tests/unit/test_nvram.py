from winbootfix.boot import nvram

OLD = """BootCurrent: 0001
Timeout: 1 seconds
BootOrder: 0001,0000,0002
Boot0000* Windows Boot Manager\tHD(1,GPT,2c3c1d52-aaaa-bbbb-cccc-0123456789ab,0x800,0x32000)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)WINDOWS.........x...B.C.D.O.B.J.E.C.T.=.{.9.d.e.a.8.6.2.c.}
Boot0001* debian\tHD(1,GPT,2c3c1d52-aaaa-bbbb-cccc-0123456789ab,0x800,0x32000)/File(\\EFI\\debian\\shimx64.efi)
Boot0002  UEFI: PXE IPv4\tPciRoot(0x0)/Pci(0x1c,0x0)/MAC(001122334455,0)/IPv4(0.0.0.00.0.0.0,0,0)
"""

NEW = """BootCurrent: 0003
BootOrder: 0003,0004
Boot0003* ubuntu  HD(1,GPT,5e7f0000-1111-2222-3333-444455556666,0x800,0x100000)/\\EFI\\ubuntu\\shimx64.efi
Boot0004* UEFI OS  HD(1,GPT,5e7f0000-1111-2222-3333-444455556666,0x800,0x100000)/\\EFI\\BOOT\\BOOTX64.EFI0000424f
"""


def test_parse_old_format():
    st = nvram.parse(OLD)
    assert st.current == "0001" and st.order == ["0001", "0000", "0002"]
    win = st.entry("0000")
    assert win.label == "Windows Boot Manager" and win.is_windows and win.active
    assert win.partnum == 1 and win.points_to("2C3C1D52-AAAA-BBBB-CCCC-0123456789AB")
    assert not st.entry("0002").active and st.entry("0002").partuuid is None
    assert [e.num for e in st.windows_entries()] == ["0000"]
    assert nvram.other_os_first(st).label == "debian"


def test_parse_new_format():
    st = nvram.parse(NEW)
    e = st.entry("0003")
    assert e.label == "ubuntu" and e.loader == r"\EFI\ubuntu\shimx64.efi"
    assert st.windows_entries() == []


def test_desired_order_keeps_grub_first():
    st = nvram.parse(OLD)
    assert nvram.desired_order(["0001", "0002"], "0005", st, windows_first=False) == ["0001", "0005", "0002"]
    assert nvram.desired_order(["0001", "0002"], "0005", st, windows_first=True) == ["0005", "0001", "0002"]
    assert nvram.desired_order([], "0005", st, windows_first=False) == ["0005"]
