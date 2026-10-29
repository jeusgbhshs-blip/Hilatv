"""SPEC chapter 4 and 5 samples parse and dump back to the same JSON."""

from __future__ import annotations

import json
from typing import Any

import pytest

from workers.schemas import BrandKit, Brief, Candidate, DirectorDecision, Shot
from workers.schemas.base import SchemaModel
from workers.schemas.tests.conftest import load_fixture

CASES: tuple[tuple[type[SchemaModel], str], ...] = (
    (BrandKit, "brand_kit.json"),
    (Brief, "brief.json"),
    (Shot, "shot.json"),
    (Candidate, "candidate.json"),
    (DirectorDecision, "director_decision.json"),
)


def _dump(model: SchemaModel) -> dict[str, Any]:
    return json.loads(model.model_dump_json())


@pytest.mark.parametrize(("model_cls", "fixture_name"), CASES)
def test_spec_example_roundtrip(model_cls: type[SchemaModel], fixture_name: str) -> None:
    payload = load_fixture(fixture_name)
    parsed = model_cls.model_validate(payload)
    assert _dump(parsed) == payload
    assert parsed.model_dump(mode="json") == payload
    again = model_cls.model_validate_json(parsed.model_dump_json())
    assert _dump(again) == payload


def test_on_screen_text_keeps_in_key() -> None:
    shot = Shot.model_validate(load_fixture("shot.json"))
    card = shot.on_screen_text[0]
    assert card.in_ == 0.8
    assert card.out == 3.8
    assert _dump(shot)["on_screen_text"][0]["in"] == 0.8


def test_candidate_params_keep_json_types() -> None:
    candidate = Candidate.model_validate(load_fixture("candidate.json"))
    assert candidate.params["seed"] == 1234
    assert candidate.params["duration"] == 5
    assert candidate.qa.scores.product_fidelity == 9
    assert candidate.qa.total == 8.8
    assert candidate.selected is True
