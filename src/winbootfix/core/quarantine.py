"""Quarantine: suspicious files are moved, never deleted, with restore files."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath

from winbootfix.core import guard

log = logging.getLogger(__name__)

DIR_NAME = "winbootfix_quarantine"


@dataclass
class QuarantinedFile:
    original: str          # Windows-style path relative to the volume root
    stored: str            # path relative to the quarantine session directory
    sha256: str
    size: int
    reason: str
    software: list[str]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Quarantine:
    def __init__(self, volume_root: Path, stamp: str | None = None):
        self.volume_root = volume_root
        self.stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = volume_root / DIR_NAME / self.stamp
        self.entries: list[QuarantinedFile] = []

    def move(self, path: Path, reason: str, software: list[str] | None = None) -> QuarantinedFile:
        guard.require_write(f"quarantine {path}")
        rel = path.relative_to(self.volume_root)
        dest = self.dir / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        entry = QuarantinedFile(
            original=str(PureWindowsPath(*rel.parts)), stored=str(Path("files") / rel),
            sha256=_sha256(path), size=path.stat().st_size, reason=reason, software=software or [],
        )
        shutil.move(str(path), str(dest))
        self.entries.append(entry)
        self._write_restore_files()
        log.info("quarantined %s -> %s", path, dest)
        return entry

    def _write_restore_files(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        manifest = {"created": self.stamp, "files": [asdict(e) for e in self.entries]}
        (self.dir / "restore.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
        cmd = ["@echo off", "rem winbootfix - put the quarantined files back (run as administrator)",
               "setlocal"]
        for e in self.entries:
            src = "%~dp0" + e.stored.replace("/", "\\")
            cmd.append(f'move /Y "{src}" "%SystemDrive%\\{e.original}"')
        cmd.append("echo Done.")
        (self.dir / "restore.cmd").write_text("\r\n".join(cmd) + "\r\n", encoding="utf-8")
        sh = ["#!/bin/sh", "# winbootfix - put the quarantined files back from Linux.",
              "# Usage: sh restore.sh /path/to/mounted/windows/partition", "set -e",
              ': "${1:?usage: restore.sh WINDOWS_MOUNTPOINT}"', 'here=$(dirname "$0")']
        for e in self.entries:
            orig = e.original.replace("\\", "/")
            sh.append(f'mv -f "$here/{e.stored}" "$1/{orig}"')
        sh.append('echo "Done."')
        (self.dir / "restore.sh").write_text("\n".join(sh) + "\n", encoding="utf-8")
