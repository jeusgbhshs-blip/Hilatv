"""Shared film fixtures for N16 tests. Pictures are drawn, never customer photos."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from workers.media.packaging import ai_label_text
from workers.qa.frames import write_mp4
from workers.workflow.store import project_path


def brief_payload() -> dict:
    return {
        "brief_id": "brief-t22",
        "raw_input": "给柱塞泵做一条产品短片",
        "goal": "产品介绍",
        "platform": ["抖音"],
        "duration_s": 6,
        "aspect_ratios": ["16:9"],
        "languages": ["zh"],
        "video_type": "product_showcase",
        "audience": "采购",
        "must_include": ["压力参数"],
        "style": "工业质感",
        "assumptions": [],
        "open_questions": [],
    }


def shot_payload(shot_id: str, *, duration_s: float, order: int) -> dict:
    return {
        "shot_id": shot_id,
        "order": order,
        "duration_s": duration_s,
        "purpose": "展示产品",
        "visual": "金属块置于车间，画面没有文字",
        "shot_size": "close_up",
        "camera": "locked_off",
        "subject_refs": ["product:HP-300"],
        "scene_ref": "scene:workshop",
        "voiceover": "这台柱塞泵按资料说明运行。",
        "on_screen_text": [],
        "transition_out": "cut",
        "generation_mode": "image_to_video",
        "status": "pending",
    }


def script_payload(shot_ids: list[str], *, duration_s: float) -> dict:
    return {
        "script_id": "script-t22",
        "brief_id": "brief-t22",
        "language": "zh",
        "sections": [],
        "shots": [
            shot_payload(shot_id, duration_s=duration_s, order=index + 1)
            for index, shot_id in enumerate(shot_ids)
        ],
    }


def brand_elements(*, logo: bool = True, cta: bool = True, ai_label: bool = True) -> list[dict]:
    rows: list[dict] = []
    if logo:
        rows.append(
            {
                "element_id": "logo",
                "kind": "corner_logo",
                "text": "",
                "start_s": 0,
                "end_s": 1,
            }
        )
    if cta:
        rows.append(
            {
                "element_id": "cta",
                "kind": "outro_cta",
                "text": "联系我们",
                "start_s": 0,
                "end_s": 1,
            }
        )
    if ai_label:
        rows.append(
            {
                "element_id": "ai",
                "kind": "ai_label",
                "text": ai_label_text(),
                "start_s": 0,
                "end_s": 1,
            }
        )
    return rows


def write_film(project_id: str, frames: list[Image.Image]) -> Path:
    folder = project_path(project_id, create=True)
    path = folder / "film.mp4"
    write_mp4(frames, path, fps=4)
    return path


def request_for(
    project_id: str,
    film: Path,
    shot_ids: list[str],
    *,
    seconds_each: float,
    elements: list[dict] | None = None,
    anchors: dict[str, str] | None = None,
    faces: dict[str, int] | None = None,
    extra: dict | None = None,
) -> dict:
    windows = []
    for index, shot_id in enumerate(shot_ids):
        windows.append(
            {
                "shot_id": shot_id,
                "start_s": round(index * seconds_each, 3),
                "end_s": round((index + 1) * seconds_each, 3),
                "anchor_uri": (anchors or {}).get(shot_id) or None,
                "expected_faces": (faces or {}).get(shot_id, 0),
                "model": "mock-image",
            }
        )
    payload = {
        "film_path": str(film),
        "shots": windows,
        "brief": brief_payload(),
        "script": script_payload(shot_ids, duration_s=max(seconds_each, 0.25)),
        "elements": brand_elements() if elements is None else elements,
    }
    if extra:
        payload.update(extra)
    payload.pop("enterprise_id", None)
    return {"project_id": project_id, "payload": payload, "attempt": 1}
