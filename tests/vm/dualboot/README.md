# Dual boot test image ("dual")

1. Install Windows on a 64 GB disk with only 40 GB for Windows:
   `WIN_ISO=Win10_x64_English.iso tests/vm/install.sh dual`
2. Install Debian 13 in the remaining free space with `preseed.cfg` (netinst ISO, kernel options
   `auto=true priority=critical preseed/file=/cdrom/preseed.cfg console=ttyS0,115200`; put the file
   on the ISO or serve it over HTTP with `preseed/url=`). GRUB becomes the first UEFI entry.
3. Run the scenario: `ISO=dist/winbootfix-*.iso tests/vm/run.sh dual dualboot`

The scenario checks that the files in `EFI/debian` and `EFI/Boot` are byte-for-byte unchanged, that
GRUB is still first in BootOrder, that the Windows entry is back, and that Debian still boots.
