"""Schedule winbootfix-post.ps1 at the next Windows logon (RunOnce)."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from winbootfix import __version__, paths
from winbootfix.core import guard
from winbootfix.engine import Action
from winbootfix.system import winpath
from winbootfix.windows.hive import Hive

RUNONCE_KEY = r"Microsoft\Windows\CurrentVersion\RunOnce"
RUNONCE_NAME = "!winbootfix"   # "!" = Windows deletes the value only once the command succeeded
TARGET_DIR = "winbootfix"


def runonce_command(letter: str) -> str:
    ps = rf"{letter}\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    script = rf"{letter}\{TARGET_DIR}\winbootfix-post.ps1"
    cmd = f'"{ps}" -NoProfile -ExecutionPolicy Bypass -File "{script}" -FromRunOnce'
    # Automated tests only (tests/vm): e.g. WINBOOTFIX_POST_EXTRA_ARGS="-Yes -NoPause"
    extra = os.environ.get("WINBOOTFIX_POST_EXTRA_ARGS", "").strip()
    if extra and all(a in ("-Yes", "-NoPause", "-SkipDism", "-SkipSfc", "-SkipGpu") for a in extra.split()):
        cmd += " " + extra
    return cmd


def files_to_copy() -> list[tuple[Path, str]]:
    win = paths.windows_dir()
    out = [(win / "winbootfix-post.ps1", "winbootfix-post.ps1"),
           (win / "winbootfix-post.cmd", "winbootfix-post.cmd")]
    for loc in sorted(paths.locales_dir().glob("*.json")):
        out.append((loc, f"locales/{loc.name}"))
    for name in ("gpu.json", "dll_db.json"):
        out.append((paths.data_file(name), f"data/{name}"))
    return out


class DeployPostScriptAction(Action):
    id = "health.post_script"
    module = "health"
    needs = frozenset({"win_rw"})
    explain_key = "action.health.post_script"

    def backup(self, ctx) -> None:
        self.software = ctx.install.config("SOFTWARE")
        if self.software is None:
            raise FileNotFoundError("SOFTWARE hive not found")
        ctx.backups.backup_file(self.software, "hive", windows_rel="Windows/System32/config/SOFTWARE")
        target = winpath.resolve(ctx.install.root, TARGET_DIR)
        ctx.backups.add("win_written", path=TARGET_DIR, existed=target is not None)

    def apply(self, ctx) -> None:
        guard.require_write("Windows partition (post-repair script)")
        root = ctx.install.root
        target = winpath.resolve_or_build(root, TARGET_DIR)
        for src, rel in files_to_copy():
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        flags = ctx.flags
        state = {
            "tool_version": __version__,
            "created": datetime.now().isoformat(timespec="seconds"),
            "language": ctx.t.lang,
            "reasons": sorted(flags.get("post_reasons", set())),
            "bcdboot": bool(flags.get("post_bcdboot")),
            "boot_set": flags.get("boot_set", "EFI"),
            "keep_bootorder": bool(flags.get("other_os_first")) and not flags.get("windows_first"),
            "quarantine": str(ctx.quarantine().dir.relative_to(root)).replace("/", "\\")
            if ctx.has_quarantine() else None,
            "findings": [f.id for f in ctx.report.findings],
        }
        (target / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        letter = ctx.install.system_letter or "C:"
        with Hive(self.software, write=True) as h:
            h.set_sz(RUNONCE_KEY, RUNONCE_NAME, runonce_command(letter))
            h.commit()

    def verify(self, ctx) -> bool:
        with Hive(self.software) as h:
            return bool(h.value(RUNONCE_KEY, RUNONCE_NAME))
