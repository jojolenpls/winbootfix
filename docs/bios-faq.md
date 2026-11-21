# BIOS / UEFI FAQ

[Français](bios-faq.fr.md)

Menu names differ between firmware versions: the paths below are the usual ones, not guarantees. They are
kept in [`bios_hints.json`](../src/winbootfix/data/bios_hints.json), which winbootfix uses for its advice.

## Boot menu keys

| Manufacturer | Enter the BIOS | One-time boot menu |
|---|---|---|
| ASUS | Del or F2 | F8 (desktop), Esc (laptop) |
| MSI | Del | F11 |
| Gigabyte / AORUS | Del | F12 |
| ASRock | F2 or Del | F11 |
| Dell | F2 | F12 |
| HP | F10 (Esc shows the startup menu) | F9 |
| Lenovo | F2, F1 (ThinkPad/ThinkCentre) or the Novo button | F12 |
| Acer | F2 | F12 (enable "F12 Boot Menu" in Main first) |
| Microsoft Surface | hold Volume Up + Power | hold Volume Down + Power |

Windows can also restart into the firmware: Settings > System > Recovery > Advanced startup > Restart now >
Troubleshoot > Advanced options > UEFI Firmware Settings.

## "No internal disk visible": VMD, Intel RST, RAID and AHCI

Many recent PCs (Intel 11th generation and later, especially laptops) put the NVMe or SATA disk behind
**Intel VMD** or **Intel RST (RAID mode)**. Windows has the driver, Linux sometimes does not: winbootfix then
sees no disk and says so (exit code 14).

| Manufacturer | Usual setting |
|---|---|
| ASUS | Advanced > PCH Storage Configuration > SATA Mode Selection: AHCI; Advanced > VMD setup menu > Enable VMD controller: Disabled |
| MSI | Settings > Advanced > Integrated Peripherals > SATA Mode: AHCI; Intel VMD technology: Disabled |
| Gigabyte | Settings > IO Ports > SATA and RST Configuration > SATA Mode Selection: AHCI; Intel VMD Technology: Disabled |
| ASRock | Advanced > Storage Configuration > SATA Mode: AHCI; VMD Configuration > Enable VMD controller: Disabled |
| Dell | Storage > SATA/NVMe Operation: AHCI/NVMe instead of "RAID On" |
| HP | Advanced > System Options > uncheck "Configure Storage Controller for Intel Optane / VMD" |
| Lenovo | Configuration > Storage: AHCI instead of "Intel RST Premium" / disable "VMD Controller" |
| Acer | Main > SATA Mode / VMD Controller (Ctrl+S on the Main tab shows it on some models) |

**Important:**

1. **Write down the original setting.**
2. Change it, start the winbootfix stick, repair.
3. **Put the original setting back before starting Windows**: Windows installed in RST/VMD mode may stop
   with `INACCESSIBLE_BOOT_DEVICE` in AHCI mode.
4. A real multi-disk RAID array must never be switched to AHCI: use the WinPE variant with the Intel RST
   driver (`build-winpe.ps1 -DriverPath`) instead.

The winbootfix ISO uses a Debian kernel that includes the VMD driver, so VMD disks are often visible without
any change; RST "RAID" mode on SATA usually is not.

## Secure Boot

The winbootfix ISO starts with Secure Boot **enabled**: it uses Debian's shim signed by Microsoft
("Microsoft Corporation UEFI CA", third-party CA).

- **"Secure Boot violation", "Image failed to verify" or nothing happens**: some PCs only trust Windows by
  default (Microsoft Surface, Lenovo/HP "Secured-core" models). In the BIOS, allow the **third-party CA**
  ("Allow Microsoft 3rd Party UEFI CA", "Microsoft & 3rd party CA" on Surface), or disable Secure Boot
  temporarily and enable it again after the repair.
- **BitLocker**: changing Secure Boot settings can make Windows ask for the BitLocker recovery key at the
  next start. Have the key ready (<https://account.microsoft.com/devices/recoverykey>).
- **Windows boot files signed in 2023**: since the BlackLotus mitigations, some firmwares no longer trust the
  2011 signature. winbootfix reads the firmware databases (db/dbx) and copies the matching set
  (`Windows\Boot\EFI` or `Windows\Boot\EFI_EX`).

| Manufacturer | Usual path |
|---|---|
| ASUS | Boot > Secure Boot > OS Type / Key Management |
| MSI | Settings > Advanced > Windows OS Configuration > Secure Boot |
| Gigabyte | Boot > Secure Boot |
| ASRock | Security > Secure Boot |
| Dell | Boot Configuration (or Secure Boot) > Enable Secure Boot |
| HP | Advanced (or Security) > Secure Boot Configuration |
| Lenovo | Security > Secure Boot |
| Acer | Boot > Secure Boot (set a supervisor password in Security first) |

## CSM / Legacy

Windows 10/11 on a GPT disk starts in **UEFI** mode: CSM (Compatibility Support Module) should be disabled
and the stick started on its "UEFI:" entry. If the stick was started in Legacy mode, winbootfix says so.
Windows installed in Legacy/MBR mode is detected but not repaired by this version.

| Manufacturer | Usual path |
|---|---|
| ASUS | Boot > CSM > Launch CSM: Disabled |
| MSI | Settings > Advanced > Windows OS Configuration > BIOS UEFI/CSM Mode: UEFI |
| Gigabyte | Boot > CSM Support: Disabled |
| ASRock | Boot > CSM: Disabled |
| Dell | Boot Configuration > Enable Legacy Option ROMs: Off |
| HP | Secure Boot Configuration > Legacy Support: Disabled |
| Lenovo | Startup > UEFI/Legacy Boot: UEFI Only |
| Acer | Boot > Boot Mode: UEFI |
