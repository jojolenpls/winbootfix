"""End-to-end pipeline on plain directories: detection result -> diagnosis -> repair -> verification."""

import json

from tests.conftest import make_args, needs_hivex
from winbootfix import health
from winbootfix.boot import diagnose as boot_diag
from winbootfix.boot import efifiles
from winbootfix.boot.bcd import validate
from winbootfix.engine import Executor, Plan, Severity
from winbootfix.health.postdeploy import RUNONCE_KEY, RUNONCE_NAME, DeployPostScriptAction
from winbootfix.system import winpath
from winbootfix.windows.hive import Hive

pytestmark = needs_hivex


def ids(plan):
    return {f.id for f in plan.findings}


def run_all(ctx, apply=True):
    plan = Plan()
    plan.extend(boot_diag.diagnose(ctx))
    plan.extend(health.diagnose(ctx))
    if ctx.flags.get("post_reasons"):
        plan.actions.append(DeployPostScriptAction())
    ctx.report.add_findings(plan.findings)
    results = Executor(ctx, apply=apply).execute(plan)
    return plan, results


def test_healthy_system_has_nothing_to_do(fake_system):
    ctx = fake_system(esp_kwargs={"bootmgr": True})
    # give the ESP a valid BCD and an NVRAM entry
    from winbootfix.boot.bcd import builder
    from winbootfix.core import guard
    p = ctx.paths
    with guard.allow_writes():
        builder.build(ctx.install.config("BCD-Template"), p["esp"] / "EFI/Microsoft/Boot/BCD",
                      (p["esp_uuid"], p["disk_uuid"]), (p["win_uuid"], p["disk_uuid"]))
    (p["esp"] / "EFI/Boot").mkdir()
    (p["esp"] / "EFI/Boot/bootx64.efi").write_bytes((p["esp"] / "EFI/Microsoft/Boot/bootmgfw.efi").read_bytes())
    num = ctx.nv.add("Windows Boot Manager", 1, p["esp_uuid"], r"\EFI\Microsoft\Boot\bootmgfw.efi")
    ctx.nv.order = [num]
    plan, results = run_all(ctx, apply=False)
    assert not plan.problems(), [f.id for f in plan.problems()]
    assert results == []
    assert {"boot.nvram_ok", "boot.bcd_ok", "boot.bootmgr_ok", "health.gpu_ok", "health.dll_ok"} <= ids(plan)


def test_missing_entry_files_and_bcd_are_repaired(fake_system):
    ctx = fake_system(esp_kwargs={"bootmgr": False, "other_os": True}, args=make_args(apply=True))
    grub_num = ctx.nv.add("debian", 1, ctx.paths["esp_uuid"], r"\EFI\debian\shimx64.efi")
    ctx.nv.order = [grub_num]
    plan, _ = run_all(ctx, apply=False)
    assert {"boot.bootmgr_missing", "boot.bcd_missing", "boot.nvram_missing", "boot.other_os"} <= ids(plan)
    assert [a.id for a in plan.actions] == ["boot.copy_files", "boot.bcd", "boot.nvram", "health.post_script"]

    ctx.flags["windows_first"] = False
    results = Executor(ctx, apply=True).execute(plan)
    assert [r.status for r in results] == ["applied"] * 4, [(r.action.id, r.error) for r in results]

    esp = ctx.paths["esp"]
    st = efifiles.status(esp)
    assert st.bootmgr_valid and st.bcd is not None
    assert winpath.resolve(esp, "EFI/Microsoft/Boot/fr-FR/bootmgfw.efi.mui")
    assert winpath.resolve(esp, "EFI/Microsoft/Boot/Fonts/wgl4_boot.ttf")
    # GRUB's fallback loader is untouched, GRUB stays first
    assert (esp / "EFI/Boot/bootx64.efi").read_bytes() == (esp / "EFI/debian/shimx64.efi").read_bytes()
    assert ctx.nv.order[0] == grub_num and len(ctx.nv.order) == 2
    new = ctx.nv.entries[ctx.nv.order[1]]
    assert new["label"] == "Windows Boot Manager" and new["partuuid"] == ctx.paths["esp_uuid"]
    assert validate.check(validate.read(st.bcd), ctx.paths["esp_uuid"], [ctx.paths["win_uuid"]]) == []
    # post-repair script scheduled, BCD refresh requested
    state = json.loads((ctx.paths["win"] / "winbootfix/state.json").read_text())
    assert state["bcdboot"] is True and state["keep_bootorder"] is True
    assert (ctx.paths["win"] / "winbootfix/winbootfix-post.ps1").is_file()
    assert (ctx.paths["win"] / "winbootfix/locales/fr.json").is_file()
    with Hive(ctx.install.config("SOFTWARE")) as h:
        cmd = h.value(RUNONCE_KEY, RUNONCE_NAME)
    assert cmd.startswith('"C:\\Windows\\System32\\WindowsPowerShell') and "-FromRunOnce" in cmd
    # backups exist
    manifest = json.loads(next(ctx.paths["backup"].rglob("manifest.json")).read_text())
    kinds = [i["kind"] for i in manifest["items"]]
    assert "esp_tar" in kinds and "nvram_created" in kinds and "hive" in kinds


def test_boot_ex_files_are_chosen_when_firmware_revoked_2011(fake_system, monkeypatch):
    from winbootfix.boot import certs
    ctx = fake_system(esp_kwargs={"bootmgr": False}, win_kwargs={"boot_ex": True}, args=make_args(apply=True))
    monkeypatch.setattr(certs, "firmware_certs", lambda: certs.FirmwareCerts(True, True, True, True))
    plan = boot_diag.diagnose(ctx)
    copy = next(a for a in plan.actions if a.id == "boot.copy_files")
    assert copy.boot_set == "EFI_EX"
    Executor(ctx, apply=True).execute(Plan(actions=[copy]))
    assert b"2023" in (ctx.paths["esp"] / "EFI/Microsoft/Boot/bootmgfw.efi").read_bytes()
    assert (ctx.paths["esp"] / "EFI/Microsoft/Boot/en-US/bootmgfw.efi.mui").read_bytes() == b"mui-ex"


def test_health_problems_detected_and_fixed(fake_system):
    ctx = fake_system(win_kwargs={"gpu_start": 4, "bad_dlls": True, "pending": True, "cbs_corrupt": True},
                      args=make_args(apply=True, command="health"))
    plan = health.diagnose(ctx)
    found = ids(plan)
    assert {"health.gpu_service_disabled", "health.dll.wintab32.dll", "health.dll.msvcp140.dll",
            "health.dll.empty.dll", "health.dll.foo64.dll", "health.pending_xml", "health.cbs_corruption"} <= found
    assert "health.dll.anycpu.dll" not in found and "health.dll.resonly.dll" not in found
    quarantined = sorted(a.rel for a in plan.actions if a.id.startswith("health.quarantine."))
    # the Microsoft DLL is never quarantined
    assert quarantined == ["Windows/SysWOW64/foo64.dll", "Windows/System32/empty.dll", "Windows/System32/wintab32.dll"]
    wintab = next(f for f in plan.findings if f.id == "health.dll.wintab32.dll")
    assert "Wacom" in wintab.params["software"]
    plan.actions.append(DeployPostScriptAction())
    results = Executor(ctx, apply=True).execute(plan)
    assert all(r.status == "applied" for r in results), [(r.action.id, r.error) for r in results]
    with Hive(ctx.install.config("SYSTEM")) as h:
        assert h.value(r"ControlSet001\Services\nvlddmkm", "Start") == 3
    qdir = next((ctx.paths["win"] / "winbootfix_quarantine").iterdir())
    restore = json.loads((qdir / "restore.json").read_text())
    assert {f["original"] for f in restore["files"]} == {"Windows\\System32\\wintab32.dll",
                                                         "Windows\\System32\\empty.dll",
                                                         "Windows\\SysWOW64\\foo64.dll"}
    assert (qdir / "restore.cmd").read_text().count("move /Y") == 3
    assert not (ctx.paths["win"] / "Windows/System32/wintab32.dll").exists()
    state = json.loads((ctx.paths["win"] / "winbootfix/state.json").read_text())
    assert set(state["reasons"]) >= {"integrity", "quarantine"}


def test_gpu_on_basic_display_and_missing_sys(fake_system):
    ctx = fake_system(win_kwargs={"gpu_sys": False})
    plan = health.diagnose(ctx)
    assert "health.gpu_sys_missing" in ids(plan)
    assert "gpu" in ctx.flags["post_reasons"]


def test_unknown_gpu_vendor_ignored(fake_system):
    ctx = fake_system(gpus=("1234", "1111"))
    plan = health.diagnose(ctx)
    assert not any(f.id.startswith("health.gpu_basic") or f.id == "health.gpu_unknown_to_windows" for f in plan.findings)


def test_critical_files_missing(fake_system):
    ctx = fake_system(win_kwargs={"missing": ("System32/hal.dll",)})
    plan = health.diagnose(ctx)
    f = next(f for f in plan.findings if f.id == "health.critical_files")
    assert f.severity == Severity.CRITICAL and "missing: System32/hal.dll" in f.details


def test_report_is_written_and_anonymised(fake_system, tmp_path):
    ctx = fake_system(esp_kwargs={"bootmgr": False})
    plan, _ = run_all(ctx, apply=False)
    ctx.report.add_system("report.disk", r"C:\Users\Jean\Desktop and /home/jean/x")
    files = ctx.report.save(tmp_path / "rep")
    text = files[0].read_text()
    assert "Jean" not in text and "jean" not in text and "<user>" in text
    data = json.loads(files[1].read_text())
    assert data["worst_severity"] == "critical"
    assert any(f["id"] == "boot.nvram_missing" for f in data["findings"])
