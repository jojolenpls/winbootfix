# winbootfix

**English** · [Français](README.fr.md)

Free and open-source tool (MIT license) that automatically repairs two common Windows 10 and 11 problems:

1. **The PC no longer starts Windows** because the "Windows Boot Manager" entry disappeared from the
   BIOS/UEFI (or because the boot files or the BCD configuration are damaged).
2. **Windows starts but works badly** after a repair or an update: graphics driver not loaded ("Microsoft
   Basic Display Adapter", white windows), `0xc000007b` "Bad Image" errors, DLL files of the wrong type or
   damaged, damaged system files.

It comes in three forms:

| Deliverable | For whom | Where |
|---|---|---|
| **Repair USB stick (ISO)** | everybody, even when Windows no longer starts | Releases: `winbootfix-X.Y.Z-amd64.iso` |
| **Linux tool `winbootfix`** | if Linux is already on the PC | [Installation](#install-the-linux-tool) |
| **Windows script `winbootfix-post.ps1`** (+ WinPE variant) | to finish the repair inside Windows | Releases: `winbootfix-windows.zip` |

> By default winbootfix **changes nothing**: it only diagnoses. Repairs happen only after your
> confirmation, and everything is backed up first. It never formats anything and never deletes a file
> (suspicious files go to quarantine).

---

## Step-by-step guide (beginners)

You need a USB stick of at least 1 GB and, if your PC no longer starts, **another computer** to prepare it.

1. **Download the ISO** from the [Releases](https://github.com/jojolenpls/winbootfix/releases) page
   (`winbootfix-X.Y.Z-amd64.iso`) and check its SHA256 sum (`.sha256` file).
2. **Prepare the USB stick** with Rufus (Windows), balenaEtcher (Windows, macOS, Linux) or Ventoy. The
   [USB stick guide](docs/usb-guide.md) explains each tool. Tip: with Rufus in "ISO mode" or with Ventoy,
   the report and the backups can be saved on the stick itself.
3. **Start the PC from the stick**: power it on while pressing the boot menu key (often F12, F11, F8 or
   Esc, see the [BIOS FAQ](docs/bios-faq.md)) and choose the entry that starts with **"UEFI:"**. Secure Boot
   can stay enabled.
4. The winbootfix menu opens by itself, in the language of your Windows (keyboard layout included):

   ```
   ┌──────────────────────────── Choice ────────────────────────────┐
   │ winbootfix - repair Windows startup and health. What do you    │
   │ want to do?                                                    │
   │                                                                │
   │        Diagnose and repair (recommended)                       │
   │        Diagnose only (changes nothing)                         │
   │        Expert mode                                             │
   │        Export the report (to share on a forum)                 │
   │        Language / Langue                                       │
   │        Command line (shell)                                    │
   │        Restart the computer                                    │
   │        Shut down the computer                                  │
   │                                                                │
   │                 <OK>                  <Back>                   │
   └────────────────────────────────────────────────────────────────┘
   ```

5. Choose **"Diagnose and repair"**. winbootfix explains what it found, then what it is going to do, in
   plain words, and asks for your permission. Example:

   ```
   What I found
   ============
   x [CRITICAL] The "Windows Boot Manager" entry is missing from the BIOS: this is why the PC no longer
   starts Windows.
       -> The entry can be recreated without touching your files.
   x [PROBLEM] The graphics driver "NVIDIA GeForce RTX 3070" is disabled (service nvlddmkm).
       -> It can be re-enabled now.
   x [PROBLEM] System32\wintab32.dll has the wrong type (x86) for this folder: programs using it fail
   with error 0xc000007b. Company: Wacom Technology Corp. Comes from: Wacom tablet driver, Huion tablet
   driver, XP-Pen tablet driver, Gaomon / Veikk tablet driver.
       -> The file can be moved to quarantine; then reinstall: Wacom tablet driver, ...

   Here is what I am going to do
   =============================
   1. Recreate the "Windows Boot Manager" startup entry in the BIOS (disk Samsung SSD 980 (500 GB,
   NVME), partition 1). Your files will not be touched.
   2. Re-enable the graphics driver "NVIDIA GeForce RTX 3070" (service nvlddmkm) so Windows loads it
   again.
   3. Move the damaged file Windows\System32\wintab32.dll to C:\winbootfix_quarantine (it is not deleted
   and can be put back).
   4. Prepare an automatic repair that will run at the next Windows sign-in (system file check, graphics
   driver).

   Before any change, a backup is made (EFI partition, boot entries, registry). Your personal files are
   not touched.
   Do you want me to do it? [y/N]
   ```

6. When it is done, choose **"Restart the computer"** and remove the stick.
7. At the first Windows sign-in, a **winbootfix** window opens by itself: it checks the system files (DISM
   then SFC), repairs the graphics driver and tells you which software to reinstall. Let it finish (30 to 60
   minutes). The PC never restarts without your agreement.

Still a problem? Choose **"Export the report"** in the menu (or take `C:\winbootfix\reports\`) and open a
["Case not covered" issue](https://github.com/jojolenpls/winbootfix/issues/new/choose). The report is
anonymised (user names, serial numbers and BitLocker keys are removed).

---

## What winbootfix does

### Startup repair (same as `bcdboot C:\Windows /s S: /f UEFI`, without Windows)

Checks: UEFI boot mode, EFI partitions (FAT32, type `c12a7328-…`), Windows partitions (NTFS with
`Windows\System32`), BitLocker, hibernation / fast startup, invisible disks (VMD/RST/RAID).

Repair in levels, each only when needed:

| Level | Problem | Repair |
|---|---|---|
| a | NVRAM entry missing, disabled or pointing elsewhere | `efibootmgr -c`; if GRUB/systemd-boot is first, it stays first (unless `--windows-first`) |
| b | `EFI\Microsoft\Boot\bootmgfw.efi` missing or damaged | copy from `Windows\Boot\EFI` (2011 or 2023 signed set depending on your firmware), fonts, resources; `EFI\Boot\bootx64.efi` only if free or already Microsoft's |
| c | `BCD` missing, unreadable or pointing to another partition | generated from `BCD-Template` (**experimental**, see [docs/BCD.md](docs/BCD.md)); Windows then writes an official store with `bcdboot` at its first start |

### Windows health (offline)

- **Graphics driver** NVIDIA / AMD / Intel, including dual-GPU laptops: service disabled (`Start=4`),
  service or `.sys` file gone, package missing from the DriverStore, card on "Microsoft Basic Display
  Adapter". `Start` is fixed immediately, the rest by the post-repair script.
- **DLLs** in `System32` / `SysWOW64`: wrong architecture (x86 in System32, x64 in SysWOW64), zero size,
  invalid header. .NET AnyCPU assemblies and resource-only DLLs are not reported. Third-party DLLs go to
  quarantine (`C:\winbootfix_quarantine\` + `restore.cmd`); Microsoft DLLs are never moved (SFC handles
  them). The [DLL → software database](src/winbootfix/data/dll_db.json) tells what to reinstall.
- **Integrity**: essential files missing or empty, stuck `pending.xml`, CBS log errors, damaged registry
  hives.

### Post-repair script (Windows)

`winbootfix-post.ps1` runs at the next sign-in (RunOnce) or by hand (double-click `winbootfix-post.cmd`):
`bcdboot` if needed, `DISM /Online /Cleanup-Image /RestoreHealth` then `sfc /scannow`, graphics driver
(re-enable, reinstall from the DriverStore, Windows Update, official signed vendor driver, DDU in Safe Mode
as a last resort), list of quarantined DLLs, final check (driver version, no `0xc000007b` error). Report in
`C:\winbootfix\reports\`.

### WinPE variant (optional)

On a Windows PC with the [Windows ADK and its WinPE add-on](https://learn.microsoft.com/windows-hardware/get-started/adk-install):

```powershell
powershell -ExecutionPolicy Bypass -File .\winpe\build-winpe.ps1
# with Intel RST/VMD drivers: -DriverPath C:\drivers\rst
```

The WinPE ISO opens a menu: repair startup (`bcdboot`, after a backup of the EFI partition), repair offline
(`DISM /Image … /RestoreHealth /Source:install.wim`, then `sfc /offbootdir`), unlock BitLocker. Volumes are
found with the storage cmdlets (language independent). Nothing from Microsoft is redistributed: you build
the image yourself.

---

## Limits

| Case | Behaviour |
|---|---|
| **BitLocker** | detected (`-FVE-FS-` signature). With the 48-digit recovery key (Expert mode > BitLocker, or `--bitlocker-key ask`) winbootfix opens the volume through dislocker. BitLocker "waiting for activation" / suspended opens without a key, read-only. Without a key: stops and explains. |
| **Old PC in BIOS/Legacy mode (MBR)** | detected and explained, **not repaired** in this version (hint: `bootrec` from the installation media). |
| **Stick started in Legacy mode on a UEFI PC** | detected: restart on the "UEFI:" entry of the stick. Windows health can still be checked. |
| **Windows on ARM64** | detected and reported, not supported. The ISO is for x86-64 PCs. |
| **Invisible disks (VMD / Intel RST / RAID)** | detected, BIOS advice per manufacturer (see the [BIOS FAQ](docs/bios-faq.md)). |
| **Hibernation / fast startup** | read-only; startup can still be repaired; to repair inside Windows you must allow the removal of the hibernation file (open session lost, files kept). |
| **Secure Boot** | the ISO boots with Secure Boot (signed shim). Some PCs (Surface, Lenovo "Secured-core") need "Microsoft 3rd-party UEFI CA" to be allowed in the BIOS. |
| **EFI partition deleted** | winbootfix never creates or formats partitions: use WinPE or ask for help. |

---

## Install the Linux tool

```sh
curl -fsSL https://raw.githubusercontent.com/jojolenpls/winbootfix/main/install.sh | sudo sh
```

or the `.deb` from the Releases (`sudo apt install ./winbootfix_X.Y.Z-1_all.deb`), or
`packaging/aur/PKGBUILD` (Arch Linux), or from the repository: `sudo make install`.
Dependencies: `python3` (≥ 3.9), `python3-hivex`, `efibootmgr`, `ntfs-3g`, `util-linux`, `dosfstools`;
optional: `whiptail`, `dislocker`.

```
sudo winbootfix                      # full diagnosis, changes nothing
sudo winbootfix --apply              # diagnose then repair, with confirmation
sudo winbootfix boot --apply --expert --esp /dev/nvme0n1p1
sudo winbootfix health
sudo winbootfix report --report-dir /media/usb
sudo winbootfix list-backups
sudo winbootfix restore /path/winbootfix-backups/20261121-130114 --apply
winbootfix --help                    # translated help (--lang en|fr)
```

Log: `/var/log/winbootfix.log`. Reports: `/var/log/winbootfix-reports/` (text + JSON).

### Exit codes

| Code | Meaning |
|---|---|
| 0 | nothing to do |
| 1 | problems found (diagnosis only) |
| 2 | repaired |
| 3 | partly repaired |
| 4 | cancelled |
| 10 | not run as root |
| 11 | not in UEFI mode / Windows installed in Legacy mode |
| 12 | no Windows found |
| 13 | BitLocker locked |
| 14 | no internal disk (VMD/RST/RAID) |
| 15 | Windows on ARM64 |
| 16 | no safe place for the backup |
| 64 | bad usage |
| 70 | internal error |

### Backups and safety

Before any change: full `tar.gz` archive of the EFI partition, `efibootmgr -v` output and `BootOrder`,
copy of every registry hive that is modified, `manifest.json` for `winbootfix restore`. From the USB stick,
backups go to persistent storage (the stick when it is FAT32/exFAT, another USB drive, or the Windows
partition); if there is none, nothing is changed.

---

## Build the ISO

```sh
docker build -t winbootfix-iso iso && docker run --rm --privileged -v "$PWD:/src" winbootfix-iso
# or, on Debian 13 as root: apt install live-build make && iso/build.sh
```

Debian 13 "trixie" live-build, hybrid UEFI (Secure Boot through the signed shim) and BIOS image, packages
pinned to a `snapshot.debian.org` date (`iso/SNAPSHOT`) and `SOURCE_DATE_EPOCH` for reproducible output.
The menu is text based (whiptail): it works on every screen, even without a graphics driver. The sources of
the Debian packages included are available on snapshot.debian.org at the date in `iso/SNAPSHOT` (exact list:
the `.packages` file of each release).

## Tests

- `make test`: unit tests (detection, BitLocker, PE headers, hives, BCD, NVRAM, translations, data files).
- `sudo make test-root`: integration on real GPT disk images (FAT32 + NTFS through ntfs-3g): full repair,
  restore, hibernation, BitLocker.
- `tests/iso/boot_smoke.sh`: boots the ISO in QEMU + OVMF with Secure Boot.
- `tests/vm/`: Windows 10 (English) and 11 (French) VMs with QEMU + OVMF + swtpm; scenarios NVRAM entry,
  EFI files, BCD, GRUB dual boot, graphics driver / x86 DLL / system file. See
  [tests/vm/README.md](tests/vm/README.md) (Windows evaluation ISOs needed, KVM recommended).
- GitHub Actions: lint, unit tests, loop integration, Pester (Windows), .deb package, ISO build and boot
  test; Releases published automatically for `vX.Y.Z` tags.

## Contributing

Add a language, extend the DLL → software database, report a case that is not covered: see
[CONTRIBUTING.md](CONTRIBUTING.md). Code architecture: [docs/architecture.md](docs/architecture.md).

## License

[MIT](LICENSE). winbootfix is not affiliated with Microsoft. Windows, BitLocker and the other names are
trademarks of their owners.
