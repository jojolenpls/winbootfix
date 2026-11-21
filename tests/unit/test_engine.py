from types import SimpleNamespace

from tests.conftest import make_args
from winbootfix.core import guard
from winbootfix.core.ui import NonInteractiveUI
from winbootfix.engine import Action, Executor, Finding, Plan, Severity


class Recorder(Action):
    explain_key = "action.boot.fallback"

    def __init__(self, ident, fail=False, deps=()):
        super().__init__()
        self.id = ident
        self.fail = fail
        self.depends_on = deps
        self.calls = []

    def backup(self, ctx):
        guard.require_write("backup")
        self.calls.append("backup")

    def apply(self, ctx):
        guard.require_write("apply")
        self.calls.append("apply")
        if self.fail:
            raise RuntimeError("boom")

    def rollback(self, ctx):
        self.calls.append("rollback")


def ctx_for(t, yes=True):
    backups = SimpleNamespace(ensure_ready=lambda: guard.require_write("ready"))
    return SimpleNamespace(ui=NonInteractiveUI(t, assume_yes=yes, color=False), t=t, backups=backups,
                           args=make_args(), prepare=lambda n: None, release=lambda n: None)


def test_dry_run_never_applies(t):
    a = Recorder("a")
    res = Executor(ctx_for(t), apply=False).execute(Plan(actions=[a]))
    assert [r.status for r in res] == ["planned"] and a.calls == []


def test_declined_confirmation(t):
    a = Recorder("a")
    res = Executor(ctx_for(t, yes=False), apply=True).execute(Plan(actions=[a]))
    assert [r.status for r in res] == ["cancelled"] and a.calls == []


def test_apply_failure_rollback_and_dependencies(t):
    a, b, c = Recorder("a", fail=True), Recorder("b", deps=("a",)), Recorder("c")
    res = Executor(ctx_for(t), apply=True).execute(Plan(actions=[a, b, c]))
    assert [r.status for r in res] == ["failed", "skipped", "applied"]
    assert a.calls == ["backup", "apply", "rollback"] and b.calls == []


def test_guard_closed_outside_executor():
    assert not guard.writes_allowed()
    try:
        guard.require_write("x")
    except guard.WriteNotAllowed:
        pass
    else:
        raise AssertionError("guard should refuse")


def test_plan_worst():
    p = Plan(findings=[Finding("a", "m", Severity.INFO, "k"), Finding("b", "m", Severity.ERROR, "k")])
    assert p.worst() == Severity.ERROR and len(p.problems()) == 1
