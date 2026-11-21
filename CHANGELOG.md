# Changelog

## 0.1.0 - unreleased

First version.

- Linux CLI `winbootfix`: diagnosis by default, `--apply` to repair with confirmation, backups and restore.
  - Startup repair: NVRAM entry (efibootmgr), EFI boot files (2011 or 2023 signed set), BCD store
    from BCD-Template (experimental), fallback `EFI\Boot\bootx64.efi` only when free or Microsoft's.
  - Windows health, offline: graphics driver services and packages, wrong-architecture / empty /
    invalid DLLs (quarantine, never deletion), signs of system file corruption.
  - Post-repair script scheduled through RunOnce.
  - Detection of BitLocker (recovery key or clear key via dislocker), hibernation / fast startup,
    VMD / RST / RAID controllers, Legacy BIOS installs, ARM64.
  - French and English, anonymised text + JSON report.
- Bootable ISO (Debian 13 live, Secure Boot through shim) with a whiptail menu.
- `winbootfix-post.ps1` (DISM, SFC, graphics driver, quarantine report, final check).
- Optional WinPE builder (`build-winpe.ps1`) using the user's own Windows ADK.
