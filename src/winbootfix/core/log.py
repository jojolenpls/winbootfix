"""Logging to /var/log/winbootfix.log (or a fallback location)."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

DEFAULT_LOG = Path("/var/log/winbootfix.log")
_log_path: Path | None = None


def setup(path: str | None = None, verbose: bool = False) -> Path:
    global _log_path
    candidates = [Path(path)] if path else [DEFAULT_LOG]
    candidates.append(Path(tempfile.gettempdir()) / "winbootfix.log")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    for cand in candidates:
        try:
            cand.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(cand, encoding="utf-8")
        except OSError:
            continue
        handler.setFormatter(fmt)
        handler.setLevel(logging.DEBUG)
        root.addHandler(handler)
        try:
            os.chmod(cand, 0o600)
        except OSError:
            pass
        _log_path = cand
        break
    if verbose:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        console.setLevel(logging.DEBUG)
        root.addHandler(console)
    logging.getLogger(__name__).info("---- winbootfix session start ----")
    return _log_path or candidates[-1]


def log_path() -> Path | None:
    return _log_path
