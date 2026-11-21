"""Graphics driver health, read offline from the SYSTEM and DRIVERS hives."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from winbootfix import paths
from winbootfix.engine import Action, Finding, Plan, Severity
from winbootfix.system import hardware, winpath
from winbootfix.windows import pe
from winbootfix.windows.hive import Hive, HiveError, current_control_set

log = logging.getLogger(__name__)

DISPLAY_CLASS = "{4d36e968-e325-11ce-bfc1-08002be10318}"
SERVICE_DISABLED = 4
CONFIGFLAG_DISABLED = 0x1


def load_db() -> dict:
    return json.loads(paths.data_file("gpu.json").read_text(encoding="utf-8"))


@dataclass
class DisplayDevice:
    hwid: str                     # VEN_10DE&DEV_2484
    instance: str
    service: str | None
    driver_key: str | None        # {class}\0000
    description: str = ""
    config_flags: int = 0
    driver_desc: str = ""
    driver_version: str = ""
    inf_path: str = ""
    provider: str = ""

    @property
    def vendor(self) -> str:
        return self.hwid[4:8].lower()


@dataclass
class ServiceInfo:
    name: str
    exists: bool
    start: int | None = None
    image_path: str | None = None
    sys_file: Path | None = None
    sys_ok: bool = False
    notes: list[str] = field(default_factory=list)


def read_devices(h: Hive, ccs: str) -> list[DisplayDevice]:
    out = []
    for hw in h.subkeys(rf"{ccs}\Enum\PCI"):
        up = hw.upper()
        if "VEN_" not in up or "DEV_" not in up:
            continue
        hwid = "&".join(p for p in up.split("&") if p.startswith(("VEN_", "DEV_")))
        for inst in h.subkeys(rf"{ccs}\Enum\PCI\{hw}"):
            base = rf"{ccs}\Enum\PCI\{hw}\{inst}"
            vals = h.values(base)
            if str(vals.get("ClassGUID", "")).lower() != DISPLAY_CLASS:
                continue
            dev = DisplayDevice(hwid=hwid, instance=f"PCI\\{hw}\\{inst}", service=vals.get("Service"),
                                driver_key=vals.get("Driver"),
                                description=str(vals.get("DeviceDesc", "")).split(";")[-1],
                                config_flags=vals.get("ConfigFlags") if isinstance(vals.get("ConfigFlags"), int) else 0)
            if dev.driver_key:
                cls = h.values(rf"{ccs}\Control\Class\{dev.driver_key}")
                dev.driver_desc = str(cls.get("DriverDesc", ""))
                dev.driver_version = str(cls.get("DriverVersion", ""))
                dev.inf_path = str(cls.get("InfPath", ""))
                dev.provider = str(cls.get("ProviderName", ""))
            out.append(dev)
    return out


def resolve_image_path(windows_dir: Path, image_path: str | None, service: str) -> Path | None:
    if not image_path:
        return winpath.resolve(windows_dir, f"System32/drivers/{service}.sys")
    p = image_path.strip().strip('"').replace("\\??\\", "")
    low = p.lower()
    for prefix in ("\\systemroot\\", "%systemroot%\\"):
        if low.startswith(prefix):
            return winpath.resolve(windows_dir, p[len(prefix):])
    if low.startswith("system32\\"):
        return winpath.resolve(windows_dir, p)
    if len(p) > 2 and p[1] == ":":
        return winpath.resolve(windows_dir.parent, p[3:])
    return winpath.resolve(windows_dir, p)


def read_service(h: Hive, ccs: str, windows_dir: Path, name: str) -> ServiceInfo:
    key = rf"{ccs}\Services\{name}"
    if not h.exists(key):
        return ServiceInfo(name, False)
    vals = h.values(key)
    info = ServiceInfo(name, True, vals.get("Start") if isinstance(vals.get("Start"), int) else None,
                       vals.get("ImagePath"))
    info.sys_file = resolve_image_path(windows_dir, info.image_path, name)
    if info.sys_file:
        p = pe.parse_file(info.sys_file)
        info.sys_ok = p.valid and p.machine == pe.MACHINE_AMD64
    return info


def driverstore_package(windows_dir: Path, inf_name: str) -> tuple[str | None, bool]:
    """Return (package folder, exists) for oemNN.inf using the DRIVERS hive."""
    drivers = winpath.resolve(windows_dir, "System32/config/DRIVERS")
    if not drivers or not inf_name:
        return None, False
    try:
        with Hive(drivers) as h:
            vals = h.values(rf"DriverDatabase\DriverInfFiles\{inf_name}")
    except HiveError:
        return None, False
    pkg = vals.get("Active")
    if not pkg:
        default = vals.get("")
        pkg = default[0] if isinstance(default, list) and default else None
    if not pkg:
        return None, False
    folder = winpath.resolve(windows_dir, f"System32/DriverStore/FileRepository/{pkg}")
    return pkg, folder is not None


class FixServiceStartAction(Action):
    module = "health"
    needs = frozenset({"win_rw"})
    explain_key = "action.health.gpu_service_start"

    def __init__(self, service: str, start: int, **params):
        super().__init__(service=service, **params)
        self.service = service
        self.start = start

    @property
    def id(self) -> str:  # type: ignore[override]
        return f"health.gpu_service_start.{self.service}"

    def backup(self, ctx) -> None:
        self.hive_path = ctx.install.config("SYSTEM")
        ctx.backups.backup_file(self.hive_path, "hive", windows_rel="Windows/System32/config/SYSTEM")

    def apply(self, ctx) -> None:
        with Hive(ctx.install.config("SYSTEM"), write=True) as h:
            ccs = current_control_set(h)
            h.set_dword(rf"{ccs}\Services\{self.service}", "Start", self.start)
            h.commit()

    def verify(self, ctx) -> bool:
        with Hive(ctx.install.config("SYSTEM")) as h:
            return h.value(rf"{current_control_set(h)}\Services\{self.service}", "Start") == self.start


def diagnose(ctx, system_hive: Path) -> Plan:
    plan = Plan()
    db = load_db()
    inst = ctx.install

    def f(fid, sev, key, advice=None, details=None, **params):
        plan.findings.append(Finding(fid, "health", sev, key, params, advice, dict(params), details or []))

    try:
        with Hive(system_hive) as h:
            ccs = current_control_set(h)
            devices = read_devices(h, ccs)
            services: dict[str, ServiceInfo] = {}
            names = {d.service for d in devices if d.service}
            names |= {s for s in db["services"] if h.exists(rf"{ccs}\Services\{s}")}
            for name in names:
                services[name.lower()] = read_service(h, ccs, inst.windows_dir, name)
    except HiveError as exc:
        f("health.gpu_unreadable", Severity.WARNING, "finding.health.gpu_unreadable", None, [str(exc)])
        return plan

    present = hardware.gpus()
    ctx.report.add_system("report.gpus", ", ".join(f"{g.vendor_name} {g.hwid}" for g in present) or "-")
    for g in present:
        if g.vendor not in db["vendors"]:
            continue
        matches = [d for d in devices if d.hwid == g.hwid]
        bound = [d for d in matches if d.service and d.service.lower() != "basicdisplay"]
        name = db["vendors"][g.vendor]["name"]
        if not matches:
            f("health.gpu_unknown_to_windows", Severity.WARNING, "finding.health.gpu_unknown",
              "advice.health.gpu_post", vendor=name, hwid=g.hwid)
        elif not bound:
            f("health.gpu_basic_display", Severity.ERROR, "finding.health.gpu_basic_display",
              "advice.health.gpu_post", vendor=name, hwid=g.hwid)
            ctx.flags.setdefault("post_reasons", set()).add("gpu")
        for d in matches:
            if d.config_flags & CONFIGFLAG_DISABLED:
                f("health.gpu_device_disabled", Severity.ERROR, "finding.health.gpu_device_disabled",
                  "advice.health.gpu_post", vendor=name, hwid=g.hwid)
                ctx.flags.setdefault("post_reasons", set()).add("gpu")

    for d in devices:
        if not d.service or d.service.lower() == "basicdisplay":
            continue
        svc = services.get(d.service.lower())
        label = d.driver_desc or d.description or d.service
        if svc is None or not svc.exists:
            f("health.gpu_service_missing", Severity.ERROR, "finding.health.gpu_service_missing",
              "advice.health.gpu_post", driver=label, service=d.service)
            ctx.flags.setdefault("post_reasons", set()).add("gpu")
            continue
        expected = db["services"].get(svc.name.lower(), {}).get("start", 3)
        if svc.start == SERVICE_DISABLED:
            f("health.gpu_service_disabled", Severity.ERROR, "finding.health.gpu_service_disabled",
              "advice.health.gpu_fix_start", driver=label, service=svc.name)
            plan.actions.append(FixServiceStartAction(svc.name, expected, driver=label))
        if svc.sys_file is None:
            f("health.gpu_sys_missing", Severity.ERROR, "finding.health.gpu_sys_missing",
              "advice.health.gpu_post", driver=label, file=svc.image_path or f"{svc.name}.sys")
            ctx.flags.setdefault("post_reasons", set()).add("gpu")
        elif not svc.sys_ok:
            f("health.gpu_sys_invalid", Severity.ERROR, "finding.health.gpu_sys_invalid",
              "advice.health.gpu_post", driver=label, file=str(svc.sys_file.name))
            ctx.flags.setdefault("post_reasons", set()).add("gpu")
        pkg, exists = driverstore_package(inst.windows_dir, d.inf_path)
        if d.inf_path and not exists:
            f("health.gpu_package_missing", Severity.WARNING, "finding.health.gpu_package_missing",
              "advice.health.gpu_download", driver=label, inf=d.inf_path)
            ctx.flags.setdefault("post_reasons", set()).add("gpu")
        elif pkg and svc.start != SERVICE_DISABLED and svc.sys_ok:
            f("health.gpu_ok", Severity.INFO, "finding.health.gpu_ok", None,
              [f"{d.hwid} {svc.name} {d.driver_version} {pkg}"], driver=label, version=d.driver_version or "?")
    return plan
