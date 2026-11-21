"""Case-insensitive path resolution on mounted NTFS volumes.

ntfs-3g and ntfs3 are case-sensitive for lookups while Windows is not, so
"Windows/System32" may really be "WINDOWS/system32" on disk. Never rely on
the exact case of a Windows path.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve(root: Path | str, relpath: str) -> Path | None:
    """Return the real path of *relpath* under *root* (case-insensitive), or None."""
    current = Path(root)
    parts = [p for p in relpath.replace("\\", "/").split("/") if p and p != "."]
    for part in parts:
        candidate = current / part
        if candidate.exists():
            current = candidate
            continue
        try:
            entries = os.listdir(current)
        except OSError:
            return None
        lower = part.lower()
        match = next((e for e in entries if e.lower() == lower), None)
        if match is None:
            return None
        current = current / match
    return current


def resolve_or_build(root: Path | str, relpath: str) -> Path:
    """Resolve the longest existing prefix, then append the remaining parts as given."""
    current = Path(root)
    parts = [p for p in relpath.replace("\\", "/").split("/") if p]
    for i, part in enumerate(parts):
        found = resolve(current, part)
        if found is None:
            return current.joinpath(*parts[i:])
        current = found
    return current


def listdir_ci(directory: Path, suffix: str | None = None) -> list[Path]:
    try:
        entries = os.listdir(directory)
    except OSError:
        return []
    out = [directory / e for e in entries]
    if suffix:
        out = [p for p in out if p.name.lower().endswith(suffix.lower())]
    return sorted(out, key=lambda p: p.name.lower())
