"""N16 samples the film on N15's aligned clip spans, not the N6 durations."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from workers.nodes.n15_compose.node import run as compose
from workers.nodes.n16_final_review.node import run
from workers.nodes.n16_final_review.sample import frames_by_shot
from workers.nodes.n16_final_review.support import brand_elements, brief_payload
from workers.nodes.n16_final_review.windows import windows_from_timeline
from workers.workflow.store import init_project

# Original storyboard is three equal 0.5s shots. Alignment stretches them.
_ORIGINAL = (0.5, 0.5, 0.5)
_ALIGNED = (1.0, 1.5, 2.0)


def test_n16_windows_follow_the_aligned_timeline(gateway, tmp_path: Path) -> None:
    init_project("n16align", sentence="给柱塞泵做一条片子", enterprise_id="ent-align")
    composed = _film(tmp_path)
    timeline = composed["timeline"]
    windows = windows_from_timeline(timeline)
    assert [item.shot_id for item in windows] == ["S01", "S02", "S03"]
    assert windows[1].start_s == 1.0
    assert windows[1].end_s == 2.5
    # 1.2s is inside aligned S02. On the original 0.5s grid it is inside S03.
    assert _owner([(item.shot_id, item.start_s, item.end_s) for item in windows], 1.2) == "S02"
    assert _owner(_original_spans(), 1.2) == "S03"
    film = Path(composed["exports"]["master"])
    grouped = frames_by_shot(film, [(item.shot_id, item.start_s, item.end_s) for item in windows])
    assert len(grouped["S02"]) >= 5
    raw = {
        "project_id": "n16align",
        "payload": {
            "film_path": str(film),
            "shots": [
                {"shot_id": "S01", "start_s": 0.0, "end_s": 0.5, "model": "mock-image"},
                {"shot_id": "S02", "start_s": 0.5, "end_s": 1.0, "model": "mock-image"},
                {"shot_id": "S03", "start_s": 1.0, "end_s": 1.5, "model": "mock-image"},
            ],
            "timeline": timeline,
            "brief": brief_payload(),
            "script": _script(_ALIGNED),
            "elements": brand_elements(),
        },
    }
    body = run(raw, gateway=gateway).payload
    rows = {item["shot_id"]: item for item in body["shots"]}
    assert rows["S02"]["start_s"] == 1.0
    assert rows["S02"]["end_s"] == 2.5
    assert rows["S02"]["frames"] >= 5
    assert rows["S03"]["frames"] >= 6
    assert rows["S02"]["model"] == "mock-image"


def _film(root: Path) -> dict:
    logo = root / "logo.png"
    Image.new("RGBA", (16, 16), (255, 255, 255, 255)).save(logo)
    edited = compose(
        {
            "project_id": "n16align",
            "payload": {
                "script": _script(_ORIGINAL),
                "aligned_script": _script(_ALIGNED),
                "work_dir": str(root / "n16align" / "n15"),
                "intro_s": 0,
                "outro_s": 0.4,
                "width": 320,
                "height": 180,
                "elements": [
                    _card("outro-logo", "outro_logo", "", logo),
                    _card("outro-cta", "outro_cta", "联系我们", logo),
                ],
            },
        },
        timeout_s=120,
        max_attempts=1,
    )
    return edited.payload


def _script(durations: tuple[float, ...]) -> dict:
    return {
        "script_id": "script-align",
        "brief_id": "brief-t22",
        "language": "zh",
        "sections": [],
        "shots": [_shot(index, duration) for index, duration in enumerate(durations, start=1)],
    }


def _shot(index: int, duration: float) -> dict:
    return {
        "shot_id": f"S0{index}",
        "order": index,
        "duration_s": duration,
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


def _card(element_id: str, kind: str, text: str, logo: Path) -> dict:
    return {
        "element_id": element_id,
        "kind": kind,
        "text": text,
        "start_s": 0.2,
        "end_s": 0.6,
        "anchor": "center",
        "y_ratio": 0.4 if kind == "outro_logo" else 0.62,
        "png_path": str(logo),
    }


def _original_spans() -> list[tuple[str, float, float]]:
    rows: list[tuple[str, float, float]] = []
    cursor = 0.0
    for index, duration in enumerate(_ORIGINAL, start=1):
        rows.append((f"S0{index}", cursor, cursor + duration))
        cursor += duration
    return rows


def _owner(spans: list[tuple[str, float, float]], timestamp: float) -> str | None:
    for shot_id, start, end in spans:
        if start <= timestamp < end:
            return shot_id
    return None
