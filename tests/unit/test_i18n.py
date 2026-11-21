import json
import re
from pathlib import Path

from winbootfix.core.i18n import Translator, detect_language, normalize

ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "locales"
PY_KEY = re.compile(r"[\"']((?:finding|advice|action|error|question|report|step|results|final|engine|ui|cli|"
                    r"argparse|menu|backup|target|restore|detect|severity|status|secureboot|bios|post|winpe)"
                    r"\.[a-z0-9_.]+)[\"']")
PS_KEY = re.compile(r"T '([a-z0-9_.]+)'")
DYNAMIC = ["severity.info", "severity.warning", "severity.error", "severity.critical",
           "status.planned", "status.applied", "status.failed", "status.skipped", "status.cancelled",
           "target.local", "target.boot_usb", "target.usb", "target.windows",
           "secureboot.enabled", "secureboot.disabled", "secureboot.setup", "secureboot.unknown",
           "bios.ahci", "finding.health.dll_wrong_arch", "finding.health.dll_empty", "finding.health.dll_invalid"]
IGNORED = {"restore.cmd", "restore.json", "restore.sh"}


def load(code):
    return json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))


def used_keys():
    keys = set(DYNAMIC)
    for p in (ROOT / "src").rglob("*.py"):
        keys |= set(PY_KEY.findall(p.read_text(encoding="utf-8")))
    for p in (ROOT / "windows").rglob("*.ps1"):
        keys |= set(PS_KEY.findall(p.read_text(encoding="utf-8")))
    gpu = json.loads((ROOT / "src/winbootfix/data/gpu.json").read_text())
    keys |= {v["clean_install_hint"] for v in gpu["vendors"].values()}
    return keys - IGNORED


def test_every_used_key_exists_in_en_and_fr():
    keys = used_keys()
    for code in ("en", "fr"):
        missing = sorted(k for k in keys if k not in load(code))
        assert not missing, f"{code}.json misses {missing}"


def test_same_keys_and_placeholders_in_every_language():
    ref = load("en")
    for path in LOCALES.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "_meta" in data and data["_meta"].get("name")
        for k, v in data.items():
            if k.startswith("_"):
                continue
            assert k in ref, f"{path.name}: unknown key {k}"
            assert set(re.findall(r"\{(\w+)\}", v)) == set(re.findall(r"\{(\w+)\}", ref[k])), f"{path.name}:{k}"
        if path.stem in ("en", "fr"):
            assert set(data) == set(ref), path.name


def test_translator_fallback_and_format(tmp_path):
    t = Translator("fr")
    assert t("ui.yes") == "Oui"
    assert "Boot0003" in t("finding.boot.nvram_ok", num="0003")
    assert t("does.not.exist") == "does.not.exist"
    assert t.set_language("xx") == "en"


def test_normalize_and_detect(monkeypatch):
    assert normalize("fr_FR.UTF-8") == "fr" and normalize("pt-BR") == "pt"
    monkeypatch.delenv("WINBOOTFIX_LANG", raising=False)
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    assert detect_language(None, "fr-FR") == "fr"
    assert detect_language("en", "fr-FR") == "en"
