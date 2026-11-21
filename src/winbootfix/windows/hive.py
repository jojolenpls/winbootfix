"""Registry hive access (hivex), with a dirty-hive safety check.

A hive is "dirty" when Windows did not flush it cleanly: its newest data
is still in the transaction logs (.LOG1/.LOG2). hivex ignores those logs,
so writing to a dirty hive could be undone or corrupted by Windows on the
next boot. We refuse to write in that case unless explicitly forced.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from winbootfix.core import guard

log = logging.getLogger(__name__)

REG_NONE, REG_SZ, REG_EXPAND_SZ, REG_BINARY, REG_DWORD = 0, 1, 2, 3, 4
REG_DWORD_BE, REG_LINK, REG_MULTI_SZ, REG_QWORD = 5, 6, 7, 11


class HiveError(RuntimeError):
    pass


@dataclass
class HeaderInfo:
    valid: bool
    seq1: int = 0
    seq2: int = 0
    major: int = 0
    minor: int = 0

    @property
    def dirty(self) -> bool:
        return self.valid and self.seq1 != self.seq2


def header_info(path: Path) -> HeaderInfo:
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
    except OSError:
        return HeaderInfo(False)
    if len(head) < 32 or head[:4] != b"regf":
        return HeaderInfo(False)
    seq1, seq2 = struct.unpack_from("<II", head, 4)
    major, minor = struct.unpack_from("<II", head, 0x14)
    return HeaderInfo(True, seq1, seq2, major, minor)


def _import_hivex():
    try:
        import hivex  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on the system
        raise HiveError("python3-hivex is not installed") from exc
    return hivex


def encode_sz(text: str) -> bytes:
    return (text + "\0").encode("utf-16-le")


def encode_multi_sz(items: list[str]) -> bytes:
    return ("".join(i + "\0" for i in items) + "\0").encode("utf-16-le")


def decode_value(vtype: int, raw: bytes) -> Any:
    if vtype in (REG_SZ, REG_EXPAND_SZ, REG_LINK):
        return raw.decode("utf-16-le", errors="replace").split("\0", 1)[0]
    if vtype == REG_MULTI_SZ:
        text = raw.decode("utf-16-le", errors="replace")
        return [s for s in text.split("\0") if s]
    if vtype == REG_DWORD and len(raw) >= 4:
        return struct.unpack_from("<I", raw)[0]
    if vtype == REG_DWORD_BE and len(raw) >= 4:
        return struct.unpack_from(">I", raw)[0]
    if vtype == REG_QWORD and len(raw) >= 8:
        return struct.unpack_from("<Q", raw)[0]
    return raw


class Hive:
    def __init__(self, path: Path, write: bool = False, force_dirty: bool = False):
        self.path = Path(path)
        self.write = write
        info = header_info(self.path)
        if not info.valid:
            raise HiveError(f"{self.path} is not a valid registry hive")
        if write:
            guard.require_write(f"registry hive {self.path}")
            if info.dirty and not force_dirty:
                raise HiveError(f"{self.path} was not cleanly closed by Windows (dirty hive)")
        hivex = _import_hivex()
        try:
            self.h = hivex.Hivex(str(self.path), write=write)
        except Exception as exc:  # hivex raises RuntimeError with errno text
            raise HiveError(f"cannot open {self.path}: {exc}") from exc
        self.dirty = info.dirty

    def __enter__(self) -> Hive:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self.h = None

    # navigation -----------------------------------------------------------
    def node(self, keypath: str):
        node = self.h.root()
        for part in [p for p in keypath.replace("/", "\\").split("\\") if p]:
            try:
                child = self.h.node_get_child(node, part)
            except RuntimeError:
                child = None
            if not child:
                return None
            node = child
        return node

    def exists(self, keypath: str) -> bool:
        return self.node(keypath) is not None

    def subkeys(self, keypath: str) -> list[str]:
        node = self.node(keypath)
        if node is None:
            return []
        return [self.h.node_name(c) for c in self.h.node_children(node)]

    def values(self, keypath: str) -> dict[str, Any]:
        node = self.node(keypath)
        if node is None:
            return {}
        out = {}
        for v in self.h.node_values(node):
            vtype, raw = self.h.value_value(v)
            out[self.h.value_key(v)] = decode_value(vtype, raw)
        return out

    def raw_value(self, keypath: str, name: str) -> tuple[int, bytes] | None:
        node = self.node(keypath)
        if node is None:
            return None
        try:
            v = self.h.node_get_value(node, name)
        except RuntimeError:
            return None
        if not v:
            return None
        return self.h.value_value(v)

    def value(self, keypath: str, name: str, default: Any = None) -> Any:
        raw = self.raw_value(keypath, name)
        if raw is None:
            return default
        return decode_value(*raw)

    # writing ---------------------------------------------------------------
    def ensure_key(self, keypath: str):
        guard.require_write(f"registry key {keypath}")
        node = self.h.root()
        for part in [p for p in keypath.replace("/", "\\").split("\\") if p]:
            try:
                child = self.h.node_get_child(node, part)
            except RuntimeError:
                child = None
            node = child if child else self.h.node_add_child(node, part)
        return node

    def set_raw(self, keypath: str, name: str, vtype: int, data: bytes) -> None:
        guard.require_write(f"registry value {keypath}\\{name}")
        if not self.write:
            raise HiveError("hive opened read-only")
        node = self.ensure_key(keypath)
        self.h.node_set_value(node, {"key": name, "t": vtype, "value": data})

    def set_dword(self, keypath: str, name: str, value: int) -> None:
        self.set_raw(keypath, name, REG_DWORD, struct.pack("<I", value))

    def set_sz(self, keypath: str, name: str, value: str, expand: bool = False) -> None:
        self.set_raw(keypath, name, REG_EXPAND_SZ if expand else REG_SZ, encode_sz(value))

    def delete_value(self, keypath: str, name: str) -> bool:
        guard.require_write(f"registry value {keypath}\\{name}")
        node = self.node(keypath)
        if node is None:
            return False
        keep = []
        found = False
        for v in self.h.node_values(node):
            key = self.h.value_key(v)
            if key.lower() == name.lower():
                found = True
                continue
            vtype, raw = self.h.value_value(v)
            keep.append({"key": key, "t": vtype, "value": raw})
        if found:
            self.h.node_set_values(node, keep)
        return found

    def commit(self) -> None:
        guard.require_write(f"registry hive {self.path}")
        self.h.commit(None)


def current_control_set(hive: Hive) -> str:
    """Name of the control set Windows boots with (Select\\Current)."""
    cur = hive.value("Select", "Current")
    if isinstance(cur, int) and 0 < cur < 1000:
        name = f"ControlSet{cur:03d}"
        if hive.exists(name):
            return name
    for cand in ("ControlSet001", "ControlSet002"):
        if hive.exists(cand):
            return cand
    raise HiveError("no ControlSet found in SYSTEM hive")
