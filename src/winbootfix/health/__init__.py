"""Module B: Windows health (graphics driver, DLLs, system files), offline."""

from __future__ import annotations

from winbootfix.engine import Finding, Plan, Severity
from winbootfix.health import dllscan, gpu, integrity


def diagnose(ctx) -> Plan:
    plan = Plan()
    system = ctx.install.config("SYSTEM")
    if system is None:
        plan.findings.append(Finding("health.no_system_hive", "health", Severity.CRITICAL,
                                     "finding.health.no_system_hive", advice_key="advice.winpe"))
        return plan
    for part in (gpu.diagnose(ctx, system), dllscan.diagnose(ctx), integrity.diagnose(ctx)):
        plan.extend(part)
    return plan
