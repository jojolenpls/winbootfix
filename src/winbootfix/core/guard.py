"""Write guard: defence in depth for the "no modification without --apply" rule.

Every function that modifies a disk, the NVRAM or a registry hive calls
:func:`require_write`. Only the executor (``engine.Executor``) opens a
write window, after the user confirmed and after the backup succeeded.
"""

from __future__ import annotations

import contextlib
import contextvars

_writes_allowed: contextvars.ContextVar[bool] = contextvars.ContextVar("winbootfix_writes", default=False)


class WriteNotAllowed(RuntimeError):
    """Raised when code tries to modify something outside a confirmed action."""


def require_write(what: str) -> None:
    if not _writes_allowed.get():
        raise WriteNotAllowed(f"refusing to modify {what}: not inside a confirmed action (--apply)")


def writes_allowed() -> bool:
    return _writes_allowed.get()


@contextlib.contextmanager
def allow_writes():
    token = _writes_allowed.set(True)
    try:
        yield
    finally:
        _writes_allowed.reset(token)
