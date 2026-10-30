"""Storyboard cards, one-shot narration edits, and the pause gate."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from gateway.adapters.mock_adapter import MockAdapter
from gateway.cache import MemoryCache
from gateway.pricing import Pricing
from gateway.router import RouteTable, default_routes_path
from gateway.service import Gateway
from gateway.store import SqlStore
from workers.nodes.n06_voiceover.node import run as run_voice
from workers.nodes.n08_keyframe.node import run as run_frames
from workers.workflow.store import init_project, project_path
from workers.workflow.storyboard import edit_voiceover, prepare_gate, public_cards
from workers.workflow.versions import atomic_write

MARKER = "分镜旁白标记甲乙丙丁"


def _gateway(tmp_path: Path) -> Gateway:
    progress = tmp_path / "progress.md"
    progress.write_text(
        "## 告警（预算超限等，由网关自动追加）\n\n<!-- hilatv:alerts -->\n\n## 每日日志\n",
        encoding="utf-8",
    )
    return Gateway(
        routes=RouteTable(default_routes_path()),
        store=SqlStore.sqlite(tmp_path / "gateway.sqlite"),
        cache=MemoryCache(),
        pricing=Pricing.load(),
        registry={"mock": MockAdapter()},
        limits_fn=lambda: (False, Decimal("0"), Decimal("0")),
        progress_path=progress,
        model_overrides_fn=lambda: {},
    )


def _shot(shot_id: str, order: int, purpose: str, voiceover: str) -> dict:
    return {
        "shot_id": shot_id,
        "order": order,
        "duration_s": 3.0,
        "purpose": purpose,
        "visual": "产品中近景，画面无任何文字、无 Logo、无价格、无电话号码。",
        "shot_size": "medium",
        "camera": "locked_off",
        "subject_refs": ["product:HP-300"],
        "scene_ref": "scene:workshop_01",
        "voiceover": voiceover,
        "on_screen_text": [{"text": "30 MPa", "style": "spec_badge", "in": 0.2, "out": 2.4}],
        "transition_out": "cut",
        "generation_mode": "image_to_video",
        "status": "pending",
    }


def _script(first: str, second: str) -> dict:
    return {
        "script_id": "script-board",
        "brief_id": "brief-board",
        "language": "zh",
        "sections": [
            {"kind": "hook", "text": first, "shot_ids": ["S01"]},
            {"kind": "cta", "text": second, "shot_ids": ["S02"]},
        ],
        "shots": [
            _shot("S01", 1, "钩子", first),
            _shot("S02", 2, "行动号召", second),
        ],
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_node(directory: Path, name: str, payload: dict) -> None:
    folder = directory / "nodes"
    folder.mkdir(parents=True, exist_ok=True)
    atomic_write(folder / f"{name}.json", (json.dumps(payload, ensure_ascii=False) + "\n").encode())


def test_edit_rewrites_one_voice_file_and_keeps_the_other(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    gateway = _gateway(tmp_path)
    project_id = "boardedit"
    spoken = ("先看这台柱塞泵。", "欢迎来厂里看设备。")
    voice = run_voice(
        {"project_id": project_id, "payload": {"script": _script(*spoken)}},
        gateway=gateway,
    )
    frames = run_frames(
        {
            "project_id": project_id,
            "payload": {"script": voice.payload["script"], "keyframe_candidates": 3},
        },
        gateway=gateway,
    )
    init_project(project_id, sentence="给我们的柱塞泵做个15秒宣传片", skip_storyboard=False)
    directory = project_path(project_id)
    state = {
        "script": voice.payload["script"],
        "voiceovers": voice.payload["voiceovers"],
        "keyframes": frames.payload["candidates"],
    }
    _write_node(
        directory,
        "n06_voiceover",
        {"script": state["script"], "voiceovers": state["voiceovers"]},
    )
    _write_node(directory, "n08_keyframe", {"keyframes": state["keyframes"]})
    prepare_gate(project_id, state, skip=False, gateway=gateway)
    before = {
        shot_id: _sha(directory / "storyboard" / shot_id / "voice.wav")
        for shot_id in ("S01", "S02")
    }
    seq = len(gateway.store.list_logs(project_id=project_id))
    edited = spoken[0] + MARKER
    result = edit_voiceover(project_id, "S01", edited, gateway=gateway)
    after = {
        shot_id: _sha(directory / "storyboard" / shot_id / "voice.wav")
        for shot_id in ("S01", "S02")
    }
    assert after["S01"] != before["S01"]
    assert after["S02"] == before["S02"]
    assert result["nodes"] == ["n06_voiceover", "n08_keyframe", "n09_keyframe_qa"]
    assert result["prompt_contains_voiceover"] is False
    assert result["visual_reviewed"] is False
    assert result["preview_status"] == "unavailable"
    assert result["keyframe_pixels"] == "未测"
    saved = json.loads((directory / "nodes" / "n06_voiceover.json").read_text(encoding="utf-8"))
    prompts = json.loads((directory / "nodes" / "n08_keyframe.json").read_text(encoding="utf-8"))
    assert any(shot["voiceover"] == edited for shot in saved["script"]["shots"])
    blob = json.dumps(prompts["keyframes"], ensure_ascii=False)
    assert MARKER not in blob
    assert "30 MPa" not in blob
    fresh = gateway.store.list_logs(project_id=project_id)[seq:]
    assert fresh
    assert {row["shot_id"] for row in fresh} == {"S01"}
    assert {row["task"] for row in fresh} <= {"tts", "asr", "image", "judge"}
    snapshot = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    assert "regen_used" not in snapshot
    budget = json.loads((directory / "regen_budget.json").read_text(encoding="utf-8"))
    assert budget["used"] == 1
    cards = snapshot["storyboard"]
    assert all(card["visual_reviewed"] is False for card in cards)
    assert all(card["frame_url"] is None for card in cards)
    assert all(card["preview_note"] == "未测" for card in cards)


def test_placeholder_frames_are_not_previews(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    gateway = _gateway(tmp_path)
    project_id = "boardpix"
    init_project(project_id, sentence="看分镜", skip_storyboard=False)
    directory = project_path(project_id)
    solid = directory / "solid.png"
    photo = directory / "photo.png"
    Image.new("RGB", (32, 24), (20, 80, 140)).save(solid)
    image = Image.new("RGB", (32, 24), (20, 80, 140))
    for x in range(8):
        for y in range(8):
            image.putpixel((x, y), (220, 180, 40))
    image.save(photo)
    script = _script("先看泵。", "请来厂。")
    voice = run_voice({"project_id": project_id, "payload": {"script": script}}, gateway=gateway)
    state = {
        "script": voice.payload["script"],
        "voiceovers": voice.payload["voiceovers"],
        "keyframes": [
            {
                "shot_id": "S01",
                "selected": True,
                "uri": str(solid),
                "model": "mock-image",
                "params": {"frame": "first", "prompt": "flat"},
            },
            {
                "shot_id": "S02",
                "selected": True,
                "uri": str(photo),
                "model": "mock-image",
                "params": {"frame": "first", "prompt": "two colors"},
            },
        ],
    }
    prepare_gate(project_id, state, skip=False, gateway=gateway)
    cards = {
        card["shot_id"]: card
        for card in json.loads((directory / "project.json").read_text(encoding="utf-8"))[
            "storyboard"
        ]
    }
    assert cards["S01"]["preview_status"] == "unavailable"
    assert cards["S01"]["visual_reviewed"] is False
    assert cards["S01"]["frame_url"] is None
    assert cards["S01"]["preview_note"] == "未测"
    assert cards["S02"]["preview_status"] == "ready"
    assert cards["S02"]["visual_reviewed"] is False
    assert cards["S02"]["preview_note"] == "未评审"
    assert cards["S02"]["frame_url"].endswith("/storyboard/S02/frame")
    served = (directory / "storyboard" / "S02").glob("frame.*")
    assert any(path.is_file() and len(path.read_bytes()) > 32 for path in served)
    assert not list((directory / "storyboard" / "S01").glob("frame.*"))


def test_public_cards_drop_a_forced_review_flag() -> None:
    cards = public_cards(
        [
            {
                "shot_id": "S01",
                "order": 1,
                "duration_s": 2,
                "purpose": "钩子",
                "voiceover": "旁白",
                "preview_status": "unavailable",
                "visual_reviewed": True,
                "frame_rel": "storyboard/S01/frame.png",
            }
        ],
        "proj",
    )
    assert cards[0]["visual_reviewed"] is False
    assert cards[0]["frame_url"] is None
    assert cards[0]["preview_note"] == "未测"


def test_edit_api_rejects_a_missing_project_and_extra_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    from app.main import app

    client = TestClient(app)
    missing = client.post("/v1/projects/missing/storyboard/S01", json={"voiceover": "改一句旁白"})
    assert missing.status_code == 404
    init_project("held", sentence="一句", skip_storyboard=False)
    directory = project_path("held")
    snapshot = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    snapshot["status"] = "paused"
    snapshot["storyboard_gate"] = "hold"
    atomic_write(
        directory / "project.json",
        (json.dumps(snapshot, ensure_ascii=False) + "\n").encode(),
    )
    extra = client.post(
        "/v1/projects/held/storyboard/S01",
        json={"voiceover": "改一句旁白", "remove_ai_label": True},
    )
    assert extra.status_code == 422
