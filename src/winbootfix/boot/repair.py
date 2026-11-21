"""Module A repair actions (levels a, b, c). Each runs only inside the executor."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from winbootfix.boot import efifiles, nvram
from winbootfix.boot.bcd import builder
from winbootfix.boot.bcd import validate as bcdvalidate
from winbootfix.core import restore
from winbootfix.engine import Action
from winbootfix.system import winpath

log = logging.getLogger(__name__)


class CopyEfiFilesAction(Action):
    """Level b: copy the Windows boot files to the ESP, like bcdboot does."""

    id = "boot.copy_files"
    module = "boot"
    risk = "medium"
    needs = frozenset({"esp_rw"})
    explain_key = "action.boot.copy_files"

    def __init__(self, items: list[efifiles.CopyItem], with_fallback: bool, boot_set: str, **params):
        super().__init__(**params)
        self.items = list(items)
        self.boot_set = boot_set
        if with_fallback:
            bootmgr = next(i for i in self.items if i.dst_rel.lower() == efifiles.BOOTMGR.lower())
            self.items.append(efifiles.CopyItem(bootmgr.src, efifiles.FALLBACK))

    def backup(self, ctx) -> None:
        self.tar = ctx.backups.backup_esp(ctx.esp_mount(rw=True), ctx.esp.partuuid)
        self.written: list[tuple[str, bool]] = []

    def apply(self, ctx) -> None:
        root = ctx.esp_mount(rw=True)
        usage = shutil.disk_usage(root)
        if usage.total > 0 and usage.free > 0 and efifiles.plan_size(self.items) > usage.free:
            raise RuntimeError(ctx.t("error.esp_full"))

        def record(rel: str, existed: bool) -> None:
            self.written.append((rel, existed))
            ctx.backups.record_esp_write(rel, existed)

        efifiles.apply_copy(root, self.items, record)
        ctx.flags["boot_set"] = self.boot_set

    def verify(self, ctx) -> bool:
        return efifiles.status(ctx.esp_mount()).bootmgr_valid

    def rollback(self, ctx) -> None:
        if getattr(self, "written", None):
            restore.restore_esp_items(ctx.esp_mount(rw=True), self.tar, self.written)


class FallbackAction(Action):
    """Add EFI/Boot/bootx64.efi (only when absent): some firmwares forget NVRAM entries."""

    id = "boot.fallback"
    module = "boot"
    needs = frozenset({"esp_rw"})
    explain_key = "action.boot.fallback"

    def backup(self, ctx) -> None:
        self.tar = ctx.backups.backup_esp(ctx.esp_mount(rw=True), ctx.esp.partuuid)

    def apply(self, ctx) -> None:
        root = ctx.esp_mount(rw=True)
        src = winpath.resolve(root, efifiles.BOOTMGR)
        if src is None:
            raise RuntimeError("bootmgfw.efi missing")
        st = efifiles.status(root)
        if not efifiles.fallback_allowed(st):
            raise RuntimeError("EFI/Boot/bootx64.efi belongs to another system")
        efifiles.apply_copy(root, [efifiles.CopyItem(src, efifiles.FALLBACK)],
                            lambda rel, existed: ctx.backups.record_esp_write(rel, existed))

    def verify(self, ctx) -> bool:
        return winpath.resolve(ctx.esp_mount(), efifiles.FALLBACK) is not None


class BuildBcdAction(Action):
    """Level c (experimental): generate EFI/Microsoft/Boot/BCD from BCD-Template."""

    id = "boot.bcd"
    module = "boot"
    risk = "high"
    experimental = True
    needs = frozenset({"esp_rw"})
    explain_key = "action.boot.bcd"

    def __init__(self, template: Path, esp_ids: tuple[str, str], win_ids: tuple[str, str],
                 locale: str, os_description: str, windows_partuuids: list[str], **params):
        super().__init__(**params)
        self.template = template
        self.esp_ids = esp_ids
        self.win_ids = win_ids
        self.locale = locale
        self.os_description = os_description
        self.windows_partuuids = windows_partuuids

    def backup(self, ctx) -> None:
        self.tar = ctx.backups.backup_esp(ctx.esp_mount(rw=True), ctx.esp.partuuid)
        self.written: list[tuple[str, bool]] = []

    def apply(self, ctx) -> None:
        root = ctx.esp_mount(rw=True)
        with tempfile.TemporaryDirectory(prefix="winbootfix-bcd-") as tmp:
            out = Path(tmp) / "BCD"
            builder.build(self.template, out, self.esp_ids, self.win_ids, self.locale, self.os_description)
            problems = bcdvalidate.check(bcdvalidate.read(out), self.esp_ids[0], self.windows_partuuids)
            if problems:
                raise RuntimeError(f"generated BCD failed validation: {', '.join(problems)}")
            boot_dir = winpath.resolve_or_build(root, efifiles.MS_BOOT)
            boot_dir.mkdir(parents=True, exist_ok=True)
            for log_name in ("BCD.LOG", "BCD.LOG1", "BCD.LOG2"):
                old = winpath.resolve(boot_dir, log_name)
                if old is not None:
                    rel = f"{efifiles.MS_BOOT}/{old.name}"
                    self.written.append((rel, True))
                    ctx.backups.record_esp_write(rel, True)
                    old.unlink()
            dst = winpath.resolve_or_build(root, efifiles.BCD)
            existed = dst.exists()
            self.written.append((efifiles.BCD, existed))
            ctx.backups.record_esp_write(efifiles.BCD, existed)
            shutil.copyfile(out, dst)
        ctx.flags["post_bcdboot"] = True
        ctx.flags.setdefault("post_reasons", set()).add("bcd")

    def verify(self, ctx) -> bool:
        path = winpath.resolve(ctx.esp_mount(), efifiles.BCD)
        return bool(path) and not bcdvalidate.check(bcdvalidate.read(path), self.esp_ids[0],
                                                    self.windows_partuuids)

    def rollback(self, ctx) -> None:
        if getattr(self, "written", None):
            restore.restore_esp_items(ctx.esp_mount(rw=True), self.tar, self.written)


class CreateEntryAction(Action):
    """Level a: recreate the "Windows Boot Manager" NVRAM entry."""

    id = "boot.nvram"
    module = "boot"
    risk = "medium"
    needs = frozenset({"nvram"})
    explain_key = "action.boot.nvram"

    def __init__(self, disk_path: str, partnum: int, partuuid: str, **params):
        super().__init__(**params)
        self.disk = disk_path
        self.partnum = partnum
        self.partuuid = partuuid
        self.created: str | None = None

    def backup(self, ctx) -> None:
        self.before = nvram.read_state()
        ctx.backups.backup_text("efibootmgr-before.txt", self.before.raw)
        ctx.backups.add("nvram_order", order_before=self.before.order)

    def apply(self, ctx) -> None:
        self.created = nvram.create_entry(self.disk, self.partnum)
        ctx.backups.add("nvram_created", num=self.created, order_before=self.before.order)
        windows_first = bool(ctx.flags.get("windows_first"))
        nvram.set_order(nvram.desired_order(self.before.order, self.created, self.before, windows_first))

    def verify(self, ctx) -> bool:
        st = nvram.read_state()
        entry = st.entry(self.created or "")
        return bool(entry and entry.points_to(self.partuuid) and entry.is_windows and entry.num in st.order)

    def rollback(self, ctx) -> None:
        if self.created:
            nvram.delete_entry(self.created)
        if getattr(self, "before", None) and self.before.order:
            nvram.set_order(self.before.order)


class FixEntryOrderAction(Action):
    """Existing Windows entry is inactive or missing from BootOrder."""

    id = "boot.nvram_order"
    module = "boot"
    needs = frozenset({"nvram"})
    explain_key = "action.boot.nvram_order"

    def __init__(self, num: str, activate: bool, **params):
        super().__init__(**params)
        self.num = num
        self.activate = activate

    def backup(self, ctx) -> None:
        self.before = nvram.read_state()
        ctx.backups.backup_text("efibootmgr-before.txt", self.before.raw)
        ctx.backups.add("nvram_order", order_before=self.before.order)

    def apply(self, ctx) -> None:
        from winbootfix.core.run import run
        if self.activate:
            run(["efibootmgr", "-q", "-a", "-b", self.num])
        if self.num not in self.before.order:
            order = nvram.desired_order(self.before.order + [self.num], self.num, self.before,
                                        bool(ctx.flags.get("windows_first")))
            nvram.set_order(order)

    def verify(self, ctx) -> bool:
        st = nvram.read_state()
        e = st.entry(self.num)
        return bool(e and e.active and self.num in st.order)

    def rollback(self, ctx) -> None:
        if getattr(self, "before", None) and self.before.order:
            nvram.set_order(self.before.order)
