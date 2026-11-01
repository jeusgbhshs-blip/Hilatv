"""Export JSON Schema for LLM structured output and later frontend types."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers.schemas.asset import Asset, Candidate, QAReport
from workers.schemas.brand import BrandKit
from workers.schemas.brief import Brief
from workers.schemas.director import DirectorDecision, RevisionDirective
from workers.schemas.generation import GenerationSettings
from workers.schemas.script import Script, Shot

JSON_SCHEMA_DIR = Path(__file__).resolve().parent / "json_schema"

EXPORT_MODELS: tuple[tuple[str, type], ...] = (
    ("BrandKit", BrandKit),
    ("Brief", Brief),
    ("GenerationSettings", GenerationSettings),
    ("Script", Script),
    ("Shot", Shot),
    ("Asset", Asset),
    ("Candidate", Candidate),
    ("QAReport", QAReport),
    ("DirectorDecision", DirectorDecision),
    ("RevisionDirective", RevisionDirective),
)


def model_json_schemas() -> dict[str, dict[str, Any]]:
    return {name: model.model_json_schema() for name, model in EXPORT_MODELS}


def export_json_schemas(dest: Path | None = None) -> dict[str, dict[str, Any]]:
    """Write one JSON Schema file per document. Returns the schemas."""

    target = dest if dest is not None else JSON_SCHEMA_DIR
    target.mkdir(parents=True, exist_ok=True)
    schemas = model_json_schemas()
    for name, schema in schemas.items():
        path = target / f"{name}.json"
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return schemas
