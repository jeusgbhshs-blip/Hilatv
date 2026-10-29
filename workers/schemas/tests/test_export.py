"""JSON Schema export stays aligned with the Pydantic models."""

from __future__ import annotations

import json
from pathlib import Path

from workers.schemas.export import (
    EXPORT_MODELS,
    JSON_SCHEMA_DIR,
    export_json_schemas,
    model_json_schemas,
)
from workers.schemas.script import GenerationMode


def test_export_writes_every_model(tmp_path: Path) -> None:
    schemas = export_json_schemas(tmp_path)
    names = {name for name, _model in EXPORT_MODELS}
    assert set(schemas) == names
    for name in names:
        written = json.loads((tmp_path / f"{name}.json").read_text(encoding="utf-8"))
        assert written == schemas[name]


def test_committed_schemas_match_models() -> None:
    fresh = model_json_schemas()
    for name, schema in fresh.items():
        committed = json.loads((JSON_SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))
        assert committed == schema


def test_shot_schema_exposes_generation_mode_and_in_key() -> None:
    shot = model_json_schemas()["Shot"]
    defs = shot.get("$defs", {})
    mode_schema = defs.get("GenerationMode", shot["properties"]["generation_mode"])
    assert set(mode_schema["enum"]) == {mode.value for mode in GenerationMode}
    text_ref = shot["properties"]["on_screen_text"]["items"]
    text_schema = defs[text_ref["$ref"].rsplit("/", 1)[-1]] if "$ref" in text_ref else text_ref
    assert "in" in text_schema["properties"]
    assert "in_" not in text_schema["properties"]
