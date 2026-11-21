"""Undo winbootfix changes from a backup directory (``winbootfix restore``)."""

from __future__ import annotations

import json
import logging
import shutil
import tarfile
from pathlib import Path

from winbootfix.core import guard
from winbootfix.system import winpath

log = logging.getLogger(__name__)


def restore_esp_items(esp_root: Path, tar_path: Path, items: list[tuple[str, bool]]) -> None:
    """Put back files listed as (relative path, existed before) from the ESP tarball."""
    guard.require_write("EFI system partition (restore)")
    with tarfile.open(tar_path, "r:gz") as tar:
        members = {m.name.lower(): m for m in tar.getmembers() if m.isfile()}
        for rel, existed in reversed(items):
            dst = winpath.resolve_or_build(esp_root, rel)
            if existed:
                member = members.get(f"esp/{rel}".lower())
                if member is None:
                    log.warning("no backup copy of %s", rel)
                    continue
                src = tar.extractfile(member)
                if src is None:
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                with open(dst, "wb") as out:
                    shutil.copyfileobj(src, out)
            elif dst.exists():
                dst.unlink()


def load_manifest(backup_dir: Path) -> dict:
    return json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))


def describe(manifest: dict) -> list[str]:
    lines = []
    for item in manifest.get("items", []):
        kind = item.get("kind")
        if kind == "esp_written":
            lines.append(f"ESP: {item['path']} ({'restore' if item['existed'] else 'remove'})")
        elif kind == "nvram_created":
            lines.append(f"NVRAM: remove Boot{item['num']}, BootOrder={','.join(item['order_before'])}")
        elif kind == "hive":
            lines.append(f"Registry: {item.get('windows_rel')}")
        elif kind == "quarantine":
            lines.append(f"Quarantine: {item.get('dir')}")
        elif kind == "win_written":
            lines.append(f"Windows: {item.get('path')} ({'restore' if item.get('existed') else 'remove'})")
    return lines


def restore_all(ctx, backup_dir: Path) -> list[str]:
    """Restore everything listed in the manifest; returns the list of errors."""
    from winbootfix.boot import nvram

    guard.require_write("restore")
    manifest = load_manifest(backup_dir)
    items = manifest.get("items", [])
    errors: list[str] = []

    esp_items = [(i["path"], i["existed"]) for i in items if i.get("kind") == "esp_written"]
    if esp_items:
        try:
            tar = backup_dir / "esp.tar.gz"
            restore_esp_items(ctx.esp_mount(rw=True), tar, esp_items)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"ESP: {exc}")

    for item in reversed(items):
        kind = item.get("kind")
        try:
            if kind == "nvram_created":
                state = nvram.read_state()
                if state.entry(item["num"]):
                    nvram.delete_entry(item["num"])
                if item.get("order_before"):
                    existing = {e.num for e in nvram.read_state().entries}
                    nvram.set_order([n for n in item["order_before"] if n in existing])
            elif kind == "hive":
                root = ctx.win_mount(rw=True)
                dst = winpath.resolve(root, item["windows_rel"])
                if dst is None:
                    raise FileNotFoundError(item["windows_rel"])
                shutil.copy2(backup_dir / item["copy"], dst)
            elif kind == "quarantine":
                root = ctx.win_mount(rw=True)
                qdir = winpath.resolve(root, item["dir"])
                if qdir is None:
                    raise FileNotFoundError(item["dir"])
                data = json.loads((qdir / "restore.json").read_text(encoding="utf-8"))
                for f in data.get("files", []):
                    src = qdir / f["stored"]
                    dst = winpath.resolve_or_build(root, f["original"].replace("\\", "/"))
                    if src.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src), str(dst))
            elif kind == "win_written":
                root = ctx.win_mount(rw=True)
                dst = winpath.resolve_or_build(root, item["path"])
                if item.get("existed") and item.get("copy"):
                    shutil.copy2(backup_dir / item["copy"], dst)
                elif not item.get("existed") and dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    else:
                        dst.unlink()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{kind}: {exc}")
    return errors
