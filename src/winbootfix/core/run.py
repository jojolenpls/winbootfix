"""Run external commands with logging."""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Sequence

log = logging.getLogger(__name__)


class CommandError(RuntimeError):
    def __init__(self, cmd: Sequence[str], returncode: int, stdout: str, stderr: str):
        self.cmd = list(cmd)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"{' '.join(self.cmd)} failed ({returncode}): {stderr.strip() or stdout.strip()}")


def which(name: str) -> str | None:
    return shutil.which(name, path="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")


def run(cmd: Sequence[str], check: bool = True, input: str | None = None,
        timeout: float | None = 300, secret: bool = False) -> subprocess.CompletedProcess:
    """Run *cmd* (never through a shell). ``secret`` hides arguments in the log."""
    shown = cmd[0] + " <hidden arguments>" if secret else " ".join(cmd)
    log.debug("run: %s", shown)
    try:
        proc = subprocess.run(list(cmd), input=input, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise CommandError(cmd if not secret else [cmd[0]], 127, "", str(exc)) from exc
    if proc.stdout:
        log.debug("stdout: %s", proc.stdout.strip()[:4000])
    if proc.stderr:
        log.debug("stderr: %s", proc.stderr.strip()[:4000])
    if check and proc.returncode != 0:
        raise CommandError(cmd if not secret else [cmd[0]], proc.returncode, proc.stdout, proc.stderr)
    return proc
