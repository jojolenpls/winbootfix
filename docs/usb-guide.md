# Making the winbootfix USB stick

[Français](usb-guide.fr.md)

You need: the ISO `winbootfix-X.Y.Z-amd64.iso` from the
[Releases](https://github.com/jojolenpls/winbootfix/releases), a USB stick of at least 1 GB (**its content
will be erased**), and any working computer (it does not have to be the broken one).

## 1. Check the download (recommended)

| System | Command |
|---|---|
| Windows (PowerShell) | `Get-FileHash .\winbootfix-X.Y.Z-amd64.iso -Algorithm SHA256` |
| macOS | `shasum -a 256 winbootfix-X.Y.Z-amd64.iso` |
| Linux | `sha256sum -c winbootfix-X.Y.Z-amd64.iso.sha256` |

The value must be the one in the `.sha256` file.

## 2. Write the stick

| Tool | System | Report and backups saved on the stick? |
|---|---|---|
| **Rufus** (recommended on Windows) | Windows | **yes** in "ISO Image mode"; no in "DD Image mode" |
| **Ventoy** | Windows, Linux | **yes** (the stick stays usable for other files and ISOs) |
| **balenaEtcher** | Windows, macOS, Linux | no (the stick is read-only): plug in a second USB drive for the backups |
| `dd` | Linux, macOS | no (same as Etcher) |

When the stick is read-only, winbootfix stores its backups on another USB drive or on the Windows
partition; if it finds no safe place, it changes nothing.

### Rufus (Windows)

1. Download Rufus from <https://rufus.ie> and start it.
2. **Device**: your USB stick. **Boot selection**: SELECT → the winbootfix ISO.
3. **Partition scheme**: GPT. **Target system**: UEFI (non CSM).
4. START. If Rufus asks, choose **"Write in ISO Image mode (Recommended)"**.

### Ventoy (Windows, Linux)

1. Install Ventoy on the stick once (<https://www.ventoy.net>), leave "Secure Boot support" enabled.
2. Copy the ISO file onto the Ventoy partition like any file.
3. At boot, Ventoy lists the ISO files: choose winbootfix. The first time with Secure Boot on, Ventoy
   asks to enrol its key ("Enroll key" then reboot) - follow its screen.

### balenaEtcher (Windows, macOS, Linux)

1. Download from <https://etcher.balena.io>, start it.
2. "Flash from file" → the ISO, "Select target" → the stick, "Flash!".

### dd (Linux / macOS, experts)

```sh
lsblk                                  # find the stick, e.g. /dev/sdb (NOT a partition like /dev/sdb1)
sudo dd if=winbootfix-X.Y.Z-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

On macOS use `diskutil list`, `diskutil unmountDisk /dev/diskN`, then `of=/dev/rdiskN bs=4m`.

## 3. Start the broken PC from the stick

1. Plug the stick into the broken PC, power it on and press the **boot menu key** repeatedly
   (see the table in the [BIOS FAQ](bios-faq.md#boot-menu-keys)).
2. Choose the entry that starts with **`UEFI:`** followed by the stick's name.
3. The winbootfix menu opens after about one minute.

Nothing happens / "Secure Boot violation"? See the [BIOS FAQ](bios-faq.md#secure-boot).

## WinPE variant

The optional WinPE ISO (made with `build-winpe.ps1`) is written to a stick the same way. With Rufus, keep
the default settings proposed for a Windows image.
