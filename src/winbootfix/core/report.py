"""Final report (text + JSON), anonymised so it can be posted on a forum."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from winbootfix import __version__
from winbootfix.core import log as wlog
from winbootfix.core.i18n import Translator
from winbootfix.engine import ActionResult, Finding, Severity

_RULES = [
    (re.compile(r"(?i)([\\/]Users[\\/])[^\\/\s\"']+"), r"\1<user>"),
    (re.compile(r"(/home/)[^/\s\"']+"), r"\1<user>"),
    (re.compile(r"\b(\d{6}-){7}\d{6}\b"), "<bitlocker-key>"),
    (re.compile(r"(?i)\b([0-9a-f]{2}:){5}[0-9a-f]{2}\b"), "<mac>"),
    (re.compile(r"(?i)(serial[^:=\n]*[:=]\s*)\S+"), r"\1<serial>"),
]


def anonymize(text: str) -> str:
    for rx, repl in _RULES:
        text = rx.sub(repl, text)
    return text


class Report:
    def __init__(self, t: Translator):
        self.t = t
        self.started = datetime.now()
        self.system: list[tuple[str, str]] = []
        self.findings: list[Finding] = []
        self.results: list[ActionResult] = []
        self.notes: list[str] = []
        self.backup_dir: str | None = None

    def add_system(self, label_key: str, value: str) -> None:
        self.system.append((label_key, value))

    def add_findings(self, findings: list[Finding]) -> None:
        known = {(f.id, tuple(sorted(map(str, f.params.items())))) for f in self.findings}
        for f in findings:
            sig = (f.id, tuple(sorted(map(str, f.params.items()))))
            if sig not in known:
                self.findings.append(f)
                known.add(sig)

    def add_results(self, results: list[ActionResult]) -> None:
        self.results.extend(results)

    def note(self, text: str) -> None:
        self.notes.append(text)

    # rendering ---------------------------------------------------------
    def render_text(self) -> str:
        t = self.t
        out = [t("report.header", version=__version__),
               t("report.date", date=self.started.strftime("%Y-%m-%d %H:%M")), ""]
        out.append(f"== {t('report.section_system')} ==")
        for key, value in self.system:
            out.append(f"  {t(key)}: {value}")
        out.append("")
        out.append(f"== {t('report.section_findings')} ==")
        if not self.findings:
            out.append("  " + t("report.no_findings"))
        for f in sorted(self.findings, key=lambda x: -x.severity):
            out.append(f"[{t(f.severity.key)}] {f.title(t)}")
            advice = f.advice(t)
            if advice:
                out.append(f"    -> {advice}")
            for d in f.details:
                out.append(f"       {d}")
        out.append("")
        if self.results:
            out.append(f"== {t('report.section_actions')} ==")
            for r in self.results:
                line = f"[{t('status.' + r.status)}] {r.action.explain(t)}"
                if r.error:
                    line += f" ({r.error})"
                out.append(line)
            out.append("")
        if self.backup_dir:
            out.append(f"== {t('report.section_backup')} ==")
            out.append(f"  {self.backup_dir}")
            out.append("")
        for n in self.notes:
            out.append(n)
        return anonymize("\n".join(out).rstrip() + "\n")

    def to_dict(self) -> dict[str, Any]:
        t = self.t
        data = {
            "tool": "winbootfix",
            "version": __version__,
            "date": self.started.isoformat(timespec="seconds"),
            "language": t.lang,
            "system": {k: v for k, v in self.system},
            "findings": [f.to_dict(t) for f in self.findings],
            "actions": [r.to_dict(t) for r in self.results],
            "backup_dir": self.backup_dir,
            "worst_severity": max((f.severity for f in self.findings), default=Severity.INFO).name.lower(),
        }
        return json.loads(anonymize(json.dumps(data, ensure_ascii=False)))

    def save(self, directory: Path) -> list[Path]:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = self.started.strftime("%Y%m%d-%H%M%S")
        txt = directory / f"winbootfix-report-{stamp}.txt"
        js = directory / f"winbootfix-report-{stamp}.json"
        txt.write_text(self.render_text(), encoding="utf-8")
        js.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written = [txt, js]
        logp = wlog.log_path()
        if logp and logp.is_file():
            dst = directory / f"winbootfix-{stamp}.log"
            try:
                dst.write_text(anonymize(logp.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
                written.append(dst)
            except OSError:
                shutil.copy2(logp, dst)
        return written
