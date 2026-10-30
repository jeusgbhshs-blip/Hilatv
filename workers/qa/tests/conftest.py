"""Shared fixtures for QA tests. The gateway never leaves the mock judge."""

from __future__ import annotations

from typing import Any

import pytest

from workers.schemas.asset import Candidate, QAReport, QAScores


@pytest.fixture(autouse=True)
def _media_stays_in_the_project(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))


class MockGateway:
    """Returns the schema-fill fingerprint the real mock judge returns."""

    def __init__(self) -> None:
        self.judges: list[dict[str, Any]] = []
        self.texts: list[str] = []

    def judge(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        self.judges.append({"prompt": prompt, **kwargs})
        return {
            "scores": {name: 0 for name in QAScores.model_fields},
            "hard_fail": [],
            "total": 0,
            "evaluator": "mock",
            "notes": "mock",
        }

    def generate_text(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        self.texts.append(prompt)
        return {"text": prompt, "mock": True, "seed": kwargs.get("seed")}


def candidate(
    uri: str,
    *,
    shot_id: str = "S01",
    seed: int = 1,
    node: str = "N8",
    model: str = "mock-image",
) -> Candidate:
    return Candidate(
        candidate_id=f"{shot_id}-{node}-{seed}-{uri[-12:]}",
        shot_id=shot_id,
        node=node,
        model=model,
        params={"seed": seed, "prompt": "steel block, no text"},
        uri=uri,
        qa=QAReport(
            scores=QAScores(
                product_fidelity=8,
                motion_quality=8,
                aesthetics=8,
                prompt_match=8,
                artifact_free=8,
            ),
            hard_fail=[],
            total=8,
            evaluator="rule-select-v0",
            notes="placeholder",
        ),
        selected=False,
    )
