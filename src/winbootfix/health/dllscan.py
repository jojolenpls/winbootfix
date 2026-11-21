"""DLL scan of System32 / SysWOW64: wrong architecture, empty or invalid PE files."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from winbootfix import paths
from winbootfix.engine import Action, Finding, Plan, Severity
from winbootfix.system import winpath
from winbootfix.windows import pe

log = logging.getLogger(__name__)


@dataclass
class DllProblem:
    path: Path
    folder: str          # system32 | syswow64
    kind: str            # wrong_arch | empty | invalid
    arch: str = ""
    company: str = ""
    microsoft: bool = False
    software: list[str] = field(default_factory=list)


def load_json(name: str) -> dict:
    return json.loads(paths.data_file(name).read_text(encoding="utf-8"))


def software_for(name: str, db: dict) -> list[str]:
    entry = db.get("dlls", {}).get(name.lower())
    if not entry:
        return []
    return entry.get("software", [])


def scan_folder(folder: Path, kind: str, allow: set[str], critical: set[str]) -> list[DllProblem]:
    expected = pe.MACHINE_AMD64 if kind == "system32" else pe.MACHINE_I386
    wrong = pe.MACHINE_I386 if kind == "system32" else pe.MACHINE_AMD64
    out = []
    for path in winpath.listdir_ci(folder, ".dll"):
        if not path.is_file() or path.name.lower() in allow:
            continue
        info = pe.parse_file(path)
        problem = None
        if info.size == 0:
            problem = "empty"
        elif not info.valid:
            problem = "invalid"
        elif info.machine == wrong and not info.is_anycpu and not info.is_resource_only:
            problem = "wrong_arch"
        elif info.machine not in (expected, wrong, pe.MACHINE_ARM64, pe.MACHINE_ARM64EC) and not info.is_resource_only:
            problem = "wrong_arch"
        if not problem:
            continue
        details = pe.parse_file(path, with_version=True) if info.valid else info
        out.append(DllProblem(path, kind, problem, info.arch if info.valid else "",
                              details.company, details.is_microsoft or path.name.lower() in critical))
    return out


class QuarantineDllAction(Action):
    module = "health"
    risk = "medium"
    needs = frozenset({"win_rw"})
    explain_key = "action.health.quarantine_dll"

    def __init__(self, problem: DllProblem, rel: str, display: str | None = None, **params):
        super().__init__(file=display or rel, **params)
        self.problem = problem
        self.rel = rel

    @property
    def id(self) -> str:  # type: ignore[override]
        return f"health.quarantine.{self.rel.lower()}"

    def backup(self, ctx) -> None:
        q = ctx.quarantine()
        ctx.backups.add("quarantine", dir=str(q.dir.relative_to(ctx.install.root)))

    def apply(self, ctx) -> None:
        path = winpath.resolve(ctx.install.root, self.rel)
        if path is None:
            raise FileNotFoundError(self.rel)
        ctx.quarantine().move(path, self.problem.kind, self.problem.software)
        ctx.flags.setdefault("post_reasons", set()).add("quarantine")

    def verify(self, ctx) -> bool:
        return winpath.resolve(ctx.install.root, self.rel) is None


def diagnose(ctx) -> Plan:
    plan = Plan()
    inst = ctx.install
    db = load_json("dll_db.json")
    allow_db = load_json("pe_allowlist.json")
    critical = {p.split("/")[-1].lower() for p in load_json("critical_files.json")["files"]}
    total = 0
    for kind, rel in (("system32", "System32"), ("syswow64", "SysWOW64")):
        folder = winpath.resolve(inst.windows_dir, rel)
        if folder is None:
            continue
        allow = {n.lower() for n in allow_db.get(kind, [])}
        for prob in scan_folder(folder, kind, allow, critical):
            total += 1
            prob.software = software_for(prob.path.name, db)
            rel_path = prob.path.relative_to(inst.root).as_posix()
            soft = ", ".join(prob.software) if prob.software else ctx.t("finding.health.dll_unknown_software")
            params = {"file": f"{rel}\\{prob.path.name}", "arch": prob.arch or "?",
                      "company": (prob.company or "?").rstrip(". "), "software": soft}
            if prob.microsoft:
                plan.findings.append(Finding(
                    f"health.dll.{prob.path.name.lower()}", "health", Severity.ERROR,
                    f"finding.health.dll_{prob.kind}", params, "advice.health.dll_system", params,
                    [str(prob.path)]))
                ctx.flags.setdefault("post_reasons", set()).add("integrity")
            else:
                plan.findings.append(Finding(
                    f"health.dll.{prob.path.name.lower()}", "health", Severity.ERROR,
                    f"finding.health.dll_{prob.kind}", params, "advice.health.dll_quarantine", params,
                    [str(prob.path)]))
                plan.actions.append(QuarantineDllAction(prob, rel_path, display=rel_path.replace("/", "\\")))
    if total == 0:
        plan.findings.append(Finding("health.dll_ok", "health", Severity.INFO, "finding.health.dll_ok"))
    return plan
