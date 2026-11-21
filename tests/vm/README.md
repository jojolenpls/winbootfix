# Windows VM tests (QEMU + OVMF + swtpm)

These tests break a real Windows installation in a virtual machine, repair it with the winbootfix ISO and
check that Windows starts again. They need hardware virtualisation (KVM), about 150 GB of disk and several
hours, so they run on a developer machine or a self-hosted runner, not on the free GitHub runners.

Needed: `qemu-system-x86_64`, `qemu-img`, `ovmf`, `swtpm`, `xorriso`, Windows 10/11 x64 ISOs (the free
90-day evaluation ISOs from Microsoft work) and, for the graphics driver scenario, the `virtio-win` ISO
(virtio-gpu display driver).

```sh
# 1. base images (unattended install, local admin "wbf", autologon, hibernation off)
WIN_ISO=Win10_22H2_English_x64.iso VIRTIO_ISO=virtio-win.iso tests/vm/install.sh win10-en
WIN_ISO=Win11_24H2_French_x64.iso  VIRTIO_ISO=virtio-win.iso tests/vm/install.sh win11-fr

# 2. scenarios (each on a copy-on-write overlay of the base image)
ISO=dist/winbootfix-0.1.0-amd64.iso tests/vm/run.sh win10-en nvram efifiles bcd health
ISO=dist/winbootfix-0.1.0-amd64.iso tests/vm/run.sh win11-fr nvram efifiles bcd health
ISO=dist/winbootfix-0.1.0-amd64.iso tests/vm/run.sh dual dualboot     # see dualboot/README.md
```

| Scenario | Broken by | Expected |
|---|---|---|
| `nvram` | `efibootmgr -B` of the Windows entry | entry recreated, Windows starts (Secure Boot on) |
| `efifiles` | entry + every file of `EFI\Microsoft\Boot` except BCD + fallback deleted | files copied back, Windows starts |
| `bcd` | `BCD` deleted | experimental store generated, Windows starts, post-repair `bcdboot` succeeds |
| `dualboot` | Windows entry deleted on a Windows + Debian disk | GRUB files byte-identical, GRUB still first, Windows entry back, Debian boots |
| `health` | display driver service `Start=4`, x86 DLL copied into System32, `winver.exe` damaged | service re-enabled, DLL quarantined, SFC repairs `winver.exe`, display driver loaded |

How it works: phase 1 boots the winbootfix live kernel with `winbootfix.test=1 winbootfix.autorun=<base64
script>`; the ISO runs the script (break + `winbootfix --apply --yes`) and prints the result on the serial
port. Phase 2 boots the disk with Secure Boot; a startup task in Windows (`guest/report.ps1`) writes markers
(`WINDOWS-BOOT-OK`, `WINDOWS-POST-DONE`, `WINDOWS-GPU-OK`, ...) to COM1.
