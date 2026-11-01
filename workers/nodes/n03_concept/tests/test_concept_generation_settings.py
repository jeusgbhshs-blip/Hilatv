"""Concept text, cards and cover calls all consume the explicit primary settings."""

import copy

import pytest

from workers.nodes.n03_concept.node import run
from workers.nodes.n03_concept.qa import QAError, require_degraded
from workers.nodes.n03_concept.schema import NodeResult
from workers.nodes.n03_concept.tests.test_node import _BRIEF


def test_concept_overrides_stale_brief_values_and_freezes_settings(gateway):
    settings = {"aspect_ratio": "21:9", "duration_s": 30}
    result = run(
        {
            "project_id": "settings-concepts",
            "payload": {"brief": {**_BRIEF, "generation_settings": settings}},
        },
        gateway=gateway,
        max_attempts=1,
    )
    concept = result.payload["concept"]
    assert concept["generation_settings"] == settings
    assert concept["duration_s"] == 30 and concept["aspect_ratio"] == "21:9"
    assert all(
        card["duration_s"] == 30 and card["aspect_ratio"] == "21:9"
        for card in concept["directions"]
    )
    assert "30 秒" in result.payload["prompt"] and "21:9" in result.payload["prompt"]
    images = [
        log
        for log in gateway.store.list_logs(project_id="settings-concepts")
        if log["task"] == "image"
    ]
    assert images and all(log["params"]["ratio"] == "21:9" for log in images)
    tampered = copy.deepcopy(result.model_dump())
    tampered["payload"]["concept"]["directions"][0]["aspect_ratio"] = "9:16"
    with pytest.raises(QAError, match="explicit setting"):
        require_degraded(NodeResult.model_validate(tampered))
