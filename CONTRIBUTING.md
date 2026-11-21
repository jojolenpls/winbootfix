# Contributing to winbootfix

[Français](CONTRIBUTING.fr.md)

Thank you! The three most useful contributions need no programming.

## 1. Report a case that is not covered

winbootfix did not repair your PC, or said something wrong?

1. Get the report: menu **"Export the report"** on the USB stick, or `/var/log/winbootfix-reports/` under
   Linux, or `C:\winbootfix\reports\` in Windows.
2. Open an issue with the **"Case not covered"** template and attach the `.txt` (and `.json`) file.

Reports are anonymised (user names, serial numbers, BitLocker keys removed). Read it before posting anyway.

## 2. Add a language

See [docs/translating.md](docs/translating.md): copy `locales/en.json`, translate the values, keep the
`{placeholders}`, run `python3 -m pytest tests/unit/test_i18n.py`, open a pull request.

## 3. Extend the DLL → software database

[`src/winbootfix/data/dll_db.json`](src/winbootfix/data/dll_db.json) tells users what to reinstall when a DLL
in System32 / SysWOW64 is wrong (example: `wintab32.dll` → graphics tablet drivers).

```json
"wintab32.dll": {"software": ["Wacom tablet driver", "Huion tablet driver"]}
```

- file name in lowercase, `software` = names a beginner can search for;
- one entry per pull request is fine; say in the description where the DLL comes from;
- `python3 -m pytest tests/unit/test_data.py` checks the format.

The other data files work the same way: `gpu.json` (graphics vendors, official driver pages),
`bios_hints.json` (BIOS menus per manufacturer), `languages.json` (Windows language and keyboard ids),
`critical_files.json`, `pe_allowlist.json` (a proof is required for an allowlist entry).

## Code

```sh
sudo apt install python3-hivex python3-pytest shellcheck gdisk dosfstools ntfs-3g
make test            # unit tests
sudo make test-root  # integration on loop devices (real FAT32 / NTFS)
make lint            # ruff + shellcheck
```

Rules:

- standard library only in `src/` (target: Python 3.9 as found on older live systems);
- every modification of a disk, the NVRAM or a hive goes through an `Action` run by the `Executor` and
  calls `core.guard.require_write()`; diagnosis code never writes;
- no dependence on Windows' language: use registry values, PE headers, GUIDs; resolve Windows paths with
  `system.winpath` (case-insensitive);
- every user-visible string is a translation key present in `en.json` and `fr.json`, in plain words;
- add a test with each change (`tests/helpers/fakewin.py` builds fake Windows installations, hives and PE
  files).

PowerShell scripts must run on Windows PowerShell 5.1; tests use Pester 5 (`tests/windows`).

## Releases

Bump `__version__` in `src/winbootfix/__init__.py`, update `CHANGELOG.md`, `packaging/debian/changelog`
and `packaging/aur/PKGBUILD`, then push a tag `vX.Y.Z`: GitHub Actions builds and publishes the ISO, its
SHA256, the `.deb`, the source archive and the Windows scripts archive.
