"""Signs of Windows system file corruption (offline)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from winbootfix import paths
from winbootfix.engine import Finding, Plan, Severity
from winbootfix.system import winpath
from winbootfix.windows import hive as hv

CBS_PATTERNS = [
    re.compile(r"Cannot repair member file", re.I),
    re.compile(r"\[SR\] Cannot repair", re.I),
    re.compile(r"Corrupt File", re.I),
    re.compile(r"CSI Payload Corrupt", re.I),
    re.compile(r"Hashes for file member .* do not match", re.I),
]
_FILE_RX = re.compile(r"([\w.-]+\.(?:dll|exe|sys|mui|cat|efi))\b", re.I)
CBS_TAIL = 8 << 20


def scan_cbs(log: Path) -> tuple[int, list[str]]:
    try:
        size = log.stat().st_size
        with open(log, "rb") as fh:
            if size > CBS_TAIL:
                fh.seek(size - CBS_TAIL)
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return 0, []
    count, files = 0, []
    for line in text.splitlines():
        if any(p.search(line) for p in CBS_PATTERNS):
            count += 1
            m = _FILE_RX.search(line)
            if m and m.group(1) not in files:
                files.append(m.group(1))
    return count, files[:15]


def diagnose(ctx) -> Plan:
    plan = Plan()
    inst = ctx.install
    win = inst.windows_dir

    def f(fid, sev, key, advice=None, details=None, **params):
        plan.findings.append(Finding(fid, "health", sev, key, params, advice, dict(params), details or []))

    crit = json.loads(paths.data_file("critical_files.json").read_text(encoding="utf-8"))
    missing, empty = [], []
    has_wow = winpath.resolve(win, "SysWOW64") is not None
    for rel in crit["files"]:
        if rel.lower().startswith("syswow64/") and not has_wow:
            continue
        p = winpath.resolve(win, rel)
        if p is None:
            missing.append(rel)
        elif p.is_file() and p.stat().st_size == 0:
            empty.append(rel)
    if missing or empty:
        f("health.critical_files", Severity.CRITICAL, "finding.health.critical_files",
          "advice.health.integrity", [f"missing: {m}" for m in missing] + [f"empty: {e}" for e in empty],
          count=len(missing) + len(empty))
        ctx.flags.setdefault("post_reasons", set()).add("integrity")

    pending = winpath.resolve(win, "WinSxS/pending.xml")
    if pending is not None:
        f("health.pending_xml", Severity.WARNING, "finding.health.pending_xml", "advice.health.pending_xml")
        ctx.flags.setdefault("post_reasons", set()).add("integrity")

    software = inst.config("SOFTWARE")
    if software:
        try:
            with hv.Hive(software) as h:
                cbs = r"Microsoft\Windows\CurrentVersion\Component Based Servicing"
                if h.exists(cbs + r"\RebootPending") or h.exists(cbs + r"\PackagesPending"):
                    f("health.reboot_pending", Severity.INFO, "finding.health.reboot_pending")
        except hv.HiveError:
            pass

    log = winpath.resolve(win, "Logs/CBS/CBS.log")
    if log is not None:
        count, files = scan_cbs(log)
        if count:
            f("health.cbs_corruption", Severity.ERROR, "finding.health.cbs_corruption",
              "advice.health.integrity", files, count=count)
            ctx.flags.setdefault("post_reasons", set()).add("integrity")

    for name in ("SYSTEM", "SOFTWARE", "SAM", "SECURITY", "DEFAULT"):
        p = inst.config(name)
        if p is None:
            continue
        info = hv.header_info(p)
        if not info.valid:
            f(f"health.hive_invalid.{name.lower()}", Severity.CRITICAL, "finding.health.hive_invalid",
              "advice.winpe", hive=name)
        elif info.dirty:
            f(f"health.hive_dirty.{name.lower()}", Severity.INFO, "finding.health.hive_dirty", None, hive=name)

    if not any(x.severity >= Severity.WARNING for x in plan.findings):
        f("health.integrity_ok", Severity.INFO, "finding.health.integrity_ok")
    return plan
