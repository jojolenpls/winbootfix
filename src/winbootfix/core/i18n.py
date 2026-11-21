"""Translations.

One flat JSON file per language in ``locales/`` (shared with the Windows
PowerShell scripts). Keys are dotted identifiers; values may contain
``{placeholders}``. English is the fallback for any missing key.
"""

from __future__ import annotations

import json
import locale
import logging
import os
from pathlib import Path

from winbootfix import paths

log = logging.getLogger(__name__)

FALLBACK = "en"


class Translator:
    def __init__(self, lang: str = FALLBACK, directory: Path | None = None):
        self.directory = directory or paths.locales_dir()
        self._fallback = self._load(FALLBACK)
        self.lang = FALLBACK
        self._strings: dict[str, str] = self._fallback
        self.set_language(lang)

    def _load(self, lang: str) -> dict[str, str]:
        path = self.directory / f"{lang}.json"
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            if lang == FALLBACK:
                raise
            log.warning("cannot load translation %s: %s", path, exc)
            return {}
        return {k: v for k, v in data.items() if not k.startswith("_") and isinstance(v, str)}

    def set_language(self, lang: str | None) -> str:
        code = normalize(lang) if lang else FALLBACK
        if code not in self.available():
            code = FALLBACK
        self.lang = code
        self._strings = self._fallback if code == FALLBACK else {**self._fallback, **self._load(code)}
        return code

    def available(self) -> dict[str, str]:
        """Language code -> native language name."""
        out = {}
        for path in sorted(self.directory.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as fh:
                    meta = json.load(fh).get("_meta", {})
            except (OSError, ValueError):
                continue
            out[path.stem] = meta.get("name", path.stem)
        return out

    def has(self, key: str) -> bool:
        return key in self._strings

    def __call__(self, key: str, **params) -> str:
        text = self._strings.get(key)
        if text is None:
            log.debug("missing translation key %s", key)
            text = key
        if params:
            try:
                text = text.format(**params)
            except (KeyError, IndexError, ValueError):
                log.warning("bad placeholders for key %s", key)
        return text


def normalize(lang: str) -> str:
    """'fr_FR.UTF-8' / 'fr-FR' / 'FR' -> 'fr'."""
    lang = lang.strip().replace("-", "_").split(".")[0].split("@")[0]
    return lang.split("_")[0].lower() if lang else FALLBACK


def detect_language(cli_lang: str | None = None, windows_lang: str | None = None) -> str:
    """--lang > $WINBOOTFIX_LANG > Windows install language > $LC_ALL/$LANG > en."""
    for cand in (cli_lang, os.environ.get("WINBOOTFIX_LANG"), windows_lang):
        if cand:
            return normalize(cand)
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var)
        if val and val not in ("C", "POSIX") and not val.startswith("C."):
            return normalize(val)
    try:
        loc = locale.getlocale()[0]
    except ValueError:
        loc = None
    return normalize(loc) if loc else FALLBACK


_current: Translator | None = None


def get() -> Translator:
    global _current
    if _current is None:
        _current = Translator(detect_language())
    return _current


def set_current(tr: Translator) -> None:
    global _current
    _current = tr


def _(key: str, **params) -> str:
    return get()(key, **params)
