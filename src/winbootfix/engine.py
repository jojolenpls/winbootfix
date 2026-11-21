"""Findings, actions and the executor that enforces the safety rules.

Pipeline: detection -> diagnosis (Findings) -> plan (Actions) -> confirmation
-> backup -> apply -> verify -> report. Only the :class:`Executor` opens a
write window (see ``core.guard``); modules never write on their own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any

from winbootfix.core import guard
from winbootfix.core.ui import Cancelled

if TYPE_CHECKING:  # pragma: no cover
    from winbootfix.core.i18n import Translator

log = logging.getLogger(__name__)


class Severity(IntEnum):
    INFO = 0
    WARNING = 1
    ERROR = 2
    CRITICAL = 3

    @property
    def key(self) -> str:
        return f"severity.{self.name.lower()}"


@dataclass
class Finding:
    id: str
    module: str
    severity: Severity
    key: str
    params: dict[str, Any] = field(default_factory=dict)
    advice_key: str | None = None
    advice_params: dict[str, Any] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)

    def title(self, t: Translator) -> str:
        return t(self.key, **self.params)

    def advice(self, t: Translator) -> str | None:
        return t(self.advice_key, **self.advice_params) if self.advice_key else None

    def to_dict(self, t: Translator) -> dict[str, Any]:
        return {
            "id": self.id,
            "module": self.module,
            "severity": self.severity.name.lower(),
            "title": self.title(t),
            "advice": self.advice(t),
            "details": self.details,
        }


class Action:
    """A single confirmed modification. Subclasses implement ``apply``."""

    id: str = "action"
    module: str = "core"
    risk: str = "low"                # low | medium | high
    needs: frozenset[str] = frozenset()  # esp_rw | win_rw | nvram
    experimental: bool = False
    depends_on: tuple[str, ...] = ()
    explain_key: str = ""

    def __init__(self, **params: Any):
        self.params = params

    def explain(self, t: Translator) -> str:
        return t(self.explain_key, **self.params)

    def backup(self, ctx) -> None:
        """Save everything ``apply`` may change. Must raise on failure."""

    def apply(self, ctx) -> None:
        raise NotImplementedError

    def verify(self, ctx) -> bool:
        return True

    def rollback(self, ctx) -> None:
        """Best-effort undo after a failure."""


@dataclass
class ActionResult:
    action: Action
    status: str  # planned | applied | failed | skipped | cancelled
    error: str | None = None

    def to_dict(self, t: Translator) -> dict[str, Any]:
        return {"id": self.action.id, "status": self.status, "explanation": self.action.explain(t),
                "error": self.error, "experimental": self.action.experimental}


@dataclass
class Plan:
    findings: list[Finding] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)

    def extend(self, other: Plan) -> None:
        self.findings.extend(other.findings)
        ids = {a.id for a in self.actions}
        self.actions.extend(a for a in other.actions if a.id not in ids)

    def worst(self) -> Severity | None:
        return max((f.severity for f in self.findings), default=None)

    def problems(self) -> list[Finding]:
        return [f for f in self.findings if f.severity >= Severity.WARNING]


class Executor:
    def __init__(self, ctx, apply: bool, expert: bool = False):
        self.ctx = ctx
        self.apply = apply
        self.expert = expert

    def _confirm_plan(self, actions: list[Action]) -> bool:
        ui, t = self.ctx.ui, self.ctx.t
        lines = []
        for i, action in enumerate(actions, 1):
            text = f"{i}. {action.explain(t)}"
            if action.experimental:
                text += "\n   " + t("engine.experimental_note")
            lines.append(text)
        lines.append("")
        lines.append(t("engine.backup_note"))
        ui.show_text(t("engine.plan_title"), "\n".join(lines))
        if self.expert:
            return True  # confirmed one by one below
        return ui.confirm(t("engine.confirm_all"), default=False)

    def execute(self, plan: Plan) -> list[ActionResult]:
        actions = list(plan.actions)
        if not actions:
            return []
        if not self.apply:
            return [ActionResult(a, "planned") for a in actions]
        try:
            if not self._confirm_plan(actions):
                return [ActionResult(a, "cancelled") for a in actions]
        except Cancelled:
            return [ActionResult(a, "cancelled") for a in actions]

        with guard.allow_writes():
            self.ctx.backups.ensure_ready()

        results: list[ActionResult] = []
        done: set[str] = set()
        for action in actions:
            missing = [d for d in action.depends_on if d not in done and any(a.id == d for a in actions)]
            if missing:
                results.append(ActionResult(action, "skipped", f"depends on {', '.join(missing)}"))
                continue
            if self.expert:
                try:
                    if not self.ctx.ui.confirm(action.explain(self.ctx.t) + "\n\n" + self.ctx.t("engine.confirm_one")):
                        results.append(ActionResult(action, "cancelled"))
                        continue
                except Cancelled:
                    results.append(ActionResult(action, "cancelled"))
                    continue
            results.append(self._run_one(action))
            if results[-1].status == "applied":
                done.add(action.id)
        return results

    def _run_one(self, action: Action) -> ActionResult:
        ctx = self.ctx
        log.info("action %s: start", action.id)
        try:
            with guard.allow_writes():
                ctx.prepare(action.needs)
                action.backup(ctx)
                action.apply(ctx)
            ok = action.verify(ctx)
            if not ok:
                raise RuntimeError("verification failed")
            log.info("action %s: applied", action.id)
            return ActionResult(action, "applied")
        except Exception as exc:  # noqa: BLE001 - report every failure, keep going
            log.exception("action %s failed", action.id)
            try:
                with guard.allow_writes():
                    action.rollback(ctx)
            except Exception:  # noqa: BLE001
                log.exception("rollback of %s failed", action.id)
            return ActionResult(action, "failed", str(exc))
        finally:
            try:
                ctx.release(action.needs)
            except Exception:  # noqa: BLE001
                log.exception("release after %s failed", action.id)
