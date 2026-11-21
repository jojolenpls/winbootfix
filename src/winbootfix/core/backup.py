"""Timestamped backups taken before any modification, plus a restore manifest."""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Any

from winbootfix import __version__
from winbootfix.core import guard

log = logging.getLogger(__name__)

MANIFEST = "manifest.json"


class NoBackupTarget(RuntimeError):
    pass


class BackupManager:
    def __init__(self, ctx):
        self.ctx = ctx
        self.dir: Path | None = None
        self.manifest: dict[str, Any] = {}
        self._esp_tar: Path | None = None

    # setup ---------------------------------------------------------------
    def ensure_ready(self) -> Path:
        if self.dir:
            return self.dir
        guard.require_write("backup directory")
        base = self._choose_base()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = base / "winbootfix-backups" / stamp
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest = {"id": stamp, "tool_version": __version__,
                         "created": datetime.now().isoformat(timespec="seconds"), "items": []}
        self._save()
        log.info("backups go to %s", self.dir)
        self.ctx.report.backup_dir = str(self.dir)
        return self.dir

    def _choose_base(self) -> Path:
        ctx, t = self.ctx, self.ctx.t
        if ctx.args.backup_dir:
            return Path(ctx.args.backup_dir)
        targets = ctx.persistent_targets()
        if targets:
            if len(targets) == 1 or not ctx.args.expert:
                chosen = targets[0]
            else:
                key = ctx.ui.choose(t("backup.choose_target"),
                                    [(str(i), t(f"target.{tg.kind}", label=tg.label))
                                     for i, tg in enumerate(targets)], default="0")
                chosen = targets[int(key)]
            ctx.ui.info(t("backup.target_chosen", label=t(f"target.{chosen.kind}", label=chosen.label)))
            if chosen.kind == "windows":
                root = ctx.win_mount(rw=True)
                ctx.keep_win_rw = True
                return root / "winbootfix"
            return chosen.path
        if ctx.args.allow_volatile_backup:
            ctx.ui.warn(t("backup.volatile_warning"))
            return Path("/run/winbootfix")
        raise NoBackupTarget(t("backup.no_target"))

    def _save(self) -> None:
        assert self.dir is not None
        (self.dir / MANIFEST).write_text(json.dumps(self.manifest, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")

    def add(self, kind: str, **info: Any) -> None:
        self.ensure_ready()
        self.manifest["items"].append({"kind": kind, **info})
        self._save()

    def set_meta(self, **info: Any) -> None:
        self.ensure_ready()
        self.manifest.update(info)
        self._save()

    # helpers -------------------------------------------------------------
    def backup_esp(self, esp_root: Path, partuuid: str | None) -> Path:
        """tar.gz of the whole EFI system partition (done once per session)."""
        self.ensure_ready()
        if self._esp_tar:
            return self._esp_tar
        assert self.dir is not None
        dest = self.dir / "esp.tar.gz"
        with tarfile.open(dest, "w:gz") as tar:
            tar.add(str(esp_root), arcname="esp")
        self._esp_tar = dest
        self.add("esp_tar", file=dest.name, partuuid=partuuid)
        return dest

    def backup_text(self, name: str, text: str) -> Path:
        self.ensure_ready()
        assert self.dir is not None
        dest = self.dir / name
        dest.write_text(text, encoding="utf-8")
        return dest

    def backup_file(self, src: Path, kind: str, **info: Any) -> Path:
        """Copy *src* into the backup directory (e.g. a registry hive)."""
        self.ensure_ready()
        assert self.dir is not None
        files = self.dir / "files"
        files.mkdir(exist_ok=True)
        dest = files / src.name
        n = 1
        while dest.exists():
            dest = files / f"{src.name}.{n}"
            n += 1
        shutil.copy2(src, dest)
        for extra in (src.with_name(src.name + ".LOG1"), src.with_name(src.name + ".LOG2")):
            if extra.exists():
                shutil.copy2(extra, files / (dest.name + extra.suffix))
        self.add(kind, copy=str(dest.relative_to(self.dir)), **info)
        return dest

    def record_esp_write(self, relpath: str, existed: bool) -> None:
        self.add("esp_written", path=relpath, existed=existed)
