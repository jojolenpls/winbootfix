"""Locate shared files (translations, Windows scripts) and package data."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"


def _candidates() -> list[Path]:
    env = os.environ.get("WINBOOTFIX_SHARE")
    cands = []
    if env:
        cands.append(Path(env))
    # Development checkout: <repo>/src/winbootfix -> <repo>
    cands.append(PACKAGE_DIR.parent.parent)
    cands.append(Path(sys.prefix) / "share" / "winbootfix")
    cands.append(Path("/usr/local/share/winbootfix"))
    cands.append(Path("/usr/share/winbootfix"))
    return cands


def share_dir() -> Path:
    """Directory containing ``locales/`` and ``windows/``."""
    for cand in _candidates():
        if (cand / "locales" / "en.json").is_file():
            return cand
    raise FileNotFoundError("winbootfix shared files (locales/en.json) not found; set WINBOOTFIX_SHARE")


def locales_dir() -> Path:
    return share_dir() / "locales"


def windows_dir() -> Path:
    return share_dir() / "windows"


def data_file(name: str) -> Path:
    return DATA_DIR / name
