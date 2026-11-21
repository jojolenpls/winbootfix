# Architecture

```
src/winbootfix/
  cli.py          command line, exit codes, translated --help
  menu.py         whiptail menu of the ISO
  context.py      session state (disks, selected Windows / ESP, mounts, backups, flags)
  detect.py       platform, disks, BitLocker, hibernation, VMD, Legacy, Windows selection
  engine.py       Finding / Action / Plan / Executor
  core/           i18n, logging, external commands, UI, report, backups, quarantine, restore, write guard
  system/         platform (efivars), hardware (sysfs DMI/PCI), disks (lsblk + blkid), NTFS boot sector,
                  mounts (ntfs-3g / vfat), BitLocker (dislocker), case-insensitive paths, backup targets
  windows/        registry hives (hivex), PE parser, Windows installation facts
  boot/           module A: diagnose, repair actions, NVRAM (efibootmgr), EFI files, certificates, bcd/
  health/         module B: graphics driver, DLL scan, integrity, post-repair script deployment
  data/           community JSON files (+ schemas)
locales/          one JSON per language, shared with the PowerShell scripts
windows/          winbootfix-post.ps1 (+ .cmd launcher), winpe/ (ADK builder, startnet.cmd, menu)
iso/              live-build configuration, build.sh, Dockerfile
```

## Pipeline and safety

```
detection -> diagnosis (Findings) -> plan (Actions) -> confirmation -> backup -> apply -> verify -> report
```

- Modules only **describe**: a `Finding` (id, severity, translated title and advice, technical details)
  and `Action`s (plain-language explanation, risk, needed resources `esp_rw` / `win_rw` / `nvram`,
  `backup()`, `apply()`, `verify()`, `rollback()`).
- Only the `Executor` modifies anything. It refuses without `--apply`, asks for confirmation (one summary
  in simple mode, one per action in expert mode), requires a **persistent** backup location first, opens
  the write window (`core.guard`) and mounts read-write only for the duration of one action. Every write
  path in the code calls `guard.require_write()`, so a bug cannot write in diagnosis mode.
- A failed action is rolled back (best effort) and the actions depending on it are skipped.
- Volumes are mounted read-only by default. Registry hives that Windows did not close cleanly (sequence
  numbers differ) are never written: their newest data is still in the `.LOG` files that hivex ignores.
- Nothing depends on Windows' language: paths are resolved case-insensitively, Windows facts come from the
  registry (build, edition, language id), never from localized strings; the WinPE script uses storage
  cmdlets, not `diskpart` output.

## Choices

- **Python 3 standard library** for binary parsing (PE, NTFS, regf headers, BCD devices), JSON data and
  tests; external tools only where Linux has the reference implementation: `efibootmgr`, `ntfs-3g`,
  `hivex`, `lsblk`/`blkid`, optional `dislocker` and `whiptail`. Hardware facts come from sysfs
  (no `dmidecode`, which kernel lockdown blocks under Secure Boot).
- **Debian 13 live-build** for the ISO: signed shim, GRUB and kernel, so the stick boots with Secure Boot
  on; packages pinned to a snapshot for reproducible builds.
- **whiptail** text menu: works on any screen without a graphics driver, tiny.
- **One JSON translation file per language** shared by Python and PowerShell.
