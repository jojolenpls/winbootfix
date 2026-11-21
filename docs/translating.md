# Adding a language / Ajouter une langue

1. Copy `locales/en.json` to `locales/<code>.json` (ISO 639-1 code: `de`, `es`, `it`, `pt`...).
   Copiez `locales/en.json` vers `locales/<code>.json`.
2. Edit `_meta`: `"name"` is the language name in that language (`"Deutsch"`), add yourself to `"authors"`.
3. Translate every value. Keep:
   - the keys unchanged;
   - the `{placeholders}` exactly as they are (same names);
   - `%(prog)s`, `%(message)s`, `%(value)r`, `%(choices)s`, `%s` in the `argparse.*` keys;
   - `ui.yes_letters` / `ui.no_letters`: the letters accepted for yes / no (e.g. `"jy"` for German).
4. Run the checks: `python3 -m pytest tests/unit/test_i18n.py` (missing keys fall back to English, but
   placeholders must match).
5. Open a pull request.

The language appears automatically in the ISO menu ("Language / Langue"), in `--lang`, in the post-repair
script and in the WinPE menu. When Windows is installed in that language, the ISO selects it by itself.

Plain words, please: the tool is meant for people who know nothing about computers. Prefer "startup files"
to "EFI binaries", "boot configuration" to "BCD" (the technical name can follow in brackets).
