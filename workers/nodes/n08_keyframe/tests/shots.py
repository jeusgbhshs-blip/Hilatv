"""Small storyboard documents for N8 and N10 tests."""

from __future__ import annotations

from typing import Any

NO_DRAWN = "画面无任何文字、无 Logo、无价格、无电话号码。"


def shot(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "shot_id": "S01",
        "order": 1,
        "duration_s": 4.0,
        "purpose": "展示核心卖点：高压",
        "visual": f"柱塞泵特写，金属表面冷光扫过。{NO_DRAWN}",
        "shot_size": "close_up",
        "camera": "locked_off",
        "subject_refs": ["product:HP-300"],
        "scene_ref": "scene:workshop_01",
        "voiceover": "Built for pressure.",
        "on_screen_text": [{"text": "30 MPa", "style": "spec_badge", "in": 0.4, "out": 3.2}],
        "transition_out": "cut",
        "generation_mode": "product_composite",
        "status": "pending",
    }
    base.update(overrides)
    return base


def storyboard(*shots: dict[str, Any]) -> dict[str, Any]:
    return {
        "script_id": "script-1",
        "brief_id": "brief-1",
        "language": "zh",
        "sections": [],
        "shots": list(shots),
    }


def request(*shots: dict[str, Any], **payload: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"script": storyboard(*shots)}
    body.update(payload)
    return {"project_id": "proj-1", "payload": body}
