"""Community data files must stay valid (minimal JSON Schema validator, stdlib only)."""

import json
import re
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[2] / "src/winbootfix/data"
PAIRS = [("dll_db.json", "dll_db"), ("gpu.json", "gpu"), ("bios_hints.json", "bios_hints"),
         ("languages.json", "languages"), ("pe_allowlist.json", "lists"), ("critical_files.json", "lists")]
TYPES = {"object": dict, "array": list, "string": str, "integer": int, "null": type(None), "boolean": bool}


def validate(value, schema, path="$"):
    types = schema.get("type")
    if types:
        names = types if isinstance(types, list) else [types]
        assert any(isinstance(value, TYPES[n]) and not (n == "integer" and isinstance(value, bool)) for n in names), \
            f"{path}: expected {types}"
    if "enum" in schema:
        assert value in schema["enum"], f"{path}: {value!r} not in {schema['enum']}"
    if "pattern" in schema and isinstance(value, str):
        assert re.search(schema["pattern"], value), f"{path}: {value!r} !~ {schema['pattern']}"
    if isinstance(value, dict):
        for req in schema.get("required", []):
            assert req in value, f"{path}: missing {req}"
        props = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        for k, v in value.items():
            if k in props:
                validate(v, props[k], f"{path}.{k}")
                continue
            matched = [s for p, s in patterns.items() if re.search(p, k)]
            for s in matched:
                validate(v, s, f"{path}.{k}")
            if not matched and schema.get("additionalProperties", True) is False:
                raise AssertionError(f"{path}: unexpected key {k!r}")
    if isinstance(value, list):
        assert len(value) >= schema.get("minItems", 0), f"{path}: too few items"
        for i, item in enumerate(value):
            if "items" in schema:
                validate(item, schema["items"], f"{path}[{i}]")


@pytest.mark.parametrize("data_file,schema", PAIRS)
def test_data_matches_schema(data_file, schema):
    data = json.loads((DATA / data_file).read_text(encoding="utf-8"))
    validate(data, json.loads((DATA / "schemas" / f"{schema}.schema.json").read_text(encoding="utf-8")))


def test_validator_rejects_bad_entry():
    schema = json.loads((DATA / "schemas/dll_db.schema.json").read_text())
    with pytest.raises(AssertionError):
        validate({"dlls": {"Bad Name.DLL": {"software": ["x"]}}}, schema)
    with pytest.raises(AssertionError):
        validate({"dlls": {"ok.dll": {"software": []}}}, schema)
