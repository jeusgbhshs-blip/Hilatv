"""Storyboard cards, one-shot narration edits, and the pause gate."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
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
from workers.workflow.storyboard import StoryboardError, edit_voiceover, prepare_gate, public_cards
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
    assert {row["task"] for row in fresh} <= {"tts", "asr", "image", "judge", "content_safety"}
    snapshot = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    assert "regen_used" not in snapshot
    budget = json.loads((directory / "regen_budget.json").read_text(encoding="utf-8"))
    assert budget["used"] == 2
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


def test_voiceover_cannot_remove_the_visible_label() -> None:
    with pytest.raises(StoryboardError, match="AI生成"):
        edit_voiceover("missing", "S01", "去掉AI生成", gateway=object())


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
    from workers.identity.session import open_session

    ident = open_session()
    client = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    missing = client.post("/v1/projects/missing/storyboard/S01", json={"voiceover": "改一句旁白"})
    assert missing.status_code == 404
    init_project("held", sentence="一句", skip_storyboard=False, enterprise_id=ident.enterprise_id)
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


def _hold(project_id: str, *, enterprise_id: str | None = None) -> Path:
    init_project(
        project_id,
        sentence="看分镜",
        skip_storyboard=False,
        enterprise_id=enterprise_id,
    )
    directory = project_path(project_id)
    script = _script("先看这台柱塞泵。", "请来厂里看设备。")
    _write_node(directory, "n06_voiceover", {"script": script, "voiceovers": []})
    folder = directory / "storyboard"
    for shot_id, payload in (("S01", b"voice-s01"), ("S02", b"voice-s02")):
        target = folder / shot_id
        target.mkdir(parents=True)
        (target / "voice.wav").write_bytes(payload)
    snapshot = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    snapshot["status"] = "paused"
    snapshot["storyboard_gate"] = "hold"
    atomic_write(
        directory / "project.json",
        (json.dumps(snapshot, ensure_ascii=False) + "\n").encode(),
    )
    return directory


def test_live_unreviewed_narration_leaves_script_and_wav(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "1")
    gateway = _gateway(tmp_path)
    directory = _hold("livemod")
    script_path = directory / "nodes" / "n06_voiceover.json"
    wav = directory / "storyboard" / "S01" / "voice.wav"
    before_script = _sha(script_path)
    before_wav = _sha(wav)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("content safety unreviewed: live moderator is not configured")

    gateway.content_safety = unavailable
    with pytest.raises(StoryboardError) as caught:
        edit_voiceover("livemod", "S01", "先看这台柱塞泵。改过", gateway=gateway)
    assert caught.value.status == 422
    assert _sha(script_path) == before_script
    assert _sha(wav) == before_wav

    def mocked(*_args, **_kwargs):
        return {"mock": True, "moderation": "mock", "reviewed": False, "passed": True}

    gateway.content_safety = mocked
    with pytest.raises(StoryboardError) as caught:
        edit_voiceover("livemod", "S01", "先看这台柱塞泵。再改", gateway=gateway)
    assert caught.value.status == 422
    assert _sha(script_path) == before_script
    assert _sha(wav) == before_wav


REFUSAL = "项目重生次数已到上限"


def _seed_budget(directory: Path, used: int) -> None:
    atomic_write(
        directory / "regen_budget.json",
        (json.dumps({"used": used, "increase_only": True}) + "\n").encode(),
    )


def _watch_budget(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Record every ledger write. The count may rise and must not fall or pass the cap."""

    from workers.qa import budget_store

    seen: list[int] = []
    real = budget_store._update

    def wrapped(path: Path, *, limit: int, take: int) -> tuple[bool, int, int]:
        taken, used, reserved = real(path, limit=limit, take=take)
        if seen:
            assert used >= seen[-1]
        assert 0 <= used <= limit
        seen.append(used)
        return taken, used, reserved

    monkeypatch.setattr(budget_store, "_update", wrapped)
    return seen


def _block_generation(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from gateway.service import get_gateway, reset_gateway

    reset_gateway()
    gateway = get_gateway()
    calls: list[str] = []

    def blocked(name: str):
        def _call(*_args: object, **_kwargs: object) -> None:
            calls.append(name)
            raise AssertionError(f"{name} must not run")

        return _call

    gateway.content_safety = blocked("content_safety")
    gateway.tts = blocked("tts")
    gateway.generate_image = blocked("image")
    gateway.generate_video = blocked("video")
    return calls


def _assert_still_paused(directory: Path, before_script: str, before_wav: dict[str, str]) -> None:
    script_path = directory / "nodes" / "n06_voiceover.json"
    assert _sha(script_path) == before_script
    for shot_id, digest in before_wav.items():
        assert _sha(directory / "storyboard" / shot_id / "voice.wav") == digest
    saved = script_path.read_text(encoding="utf-8")
    assert "改过一句" not in saved
    snapshot = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    assert snapshot["status"] == "paused"
    assert snapshot.get("storyboard_gate") == "hold"
    assert snapshot.get("storyboard_editing") is not True
    assert not snapshot.get("deliverable")
    assert "regen_used" not in snapshot
    assert "改过一句" not in json.dumps(snapshot, ensure_ascii=False)
    assert not (directory / "nodes" / "n08_keyframe.json").is_file()
    assert not (directory / "storyboard" / "index.json").is_file()
    assert not list(directory.glob("storyboard/*/frame.*"))
    assert not (directory / "playback" / "master.mp4").is_file()
    assert not (directory / "render" / "n15" / "master.mp4").is_file()


def _plant_lower_budget(directory: Path) -> str:
    """A version that claims ``used`` is 0. Restoring it must not shrink the live ledger."""

    from workers.workflow.store import locked_project
    from workers.workflow.versions import commit_locked

    with locked_project(directory.name) as folder:
        snapshot = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        snapshot["regen_used"] = 0
        manifest = commit_locked(
            folder,
            snapshot,
            instruction="改旁白之前",
            quality_pass=False,
            concept_degraded=False,
            executed=[],
            video_shots=[],
            decisions=[],
            shot_reviews=[],
            regen_used=0,
        )
    version_id = manifest["version_id"]
    decoy = directory / "versions" / version_id / "regen_budget.json"
    decoy.write_text(
        json.dumps({"used": 0, "limit": 1, "increase_only": True}) + "\n",
        encoding="utf-8",
    )
    return version_id


def test_one_remaining_regen_refuses_without_charging(tmp_path, monkeypatch) -> None:
    """A narration edit needs two takes. One left means neither is taken."""

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "2")
    monkeypatch.setenv("HILATV_LIVE", "0")
    from workers.identity.session import open_session

    owner = open_session()
    project_id = "oneleft"
    directory = _hold(project_id, enterprise_id=owner.enterprise_id)
    _seed_budget(directory, 1)
    version_id = _plant_lower_budget(directory)
    seen = _watch_budget(monkeypatch)
    calls = _block_generation(monkeypatch)
    script_path = directory / "nodes" / "n06_voiceover.json"
    before_script = _sha(script_path)
    before_wav = {
        shot_id: _sha(directory / "storyboard" / shot_id / "voice.wav")
        for shot_id in ("S01", "S02")
    }
    from app.main import app
    from gateway.service import reset_gateway

    try:
        with TestClient(app) as anon:
            bare = anon.post(
                f"/v1/projects/{project_id}/storyboard/S01",
                json={"voiceover": "先看这台柱塞泵。改过一句"},
            )
        assert bare.status_code == 401
        assert bare.json()["detail"] == "需要登录"
        stranger = open_session()
        with TestClient(app, headers={"Authorization": f"Bearer {stranger.token}"}) as other:
            hidden = other.post(
                f"/v1/projects/{project_id}/storyboard/S01",
                json={"voiceover": "先看这台柱塞泵。改过一句"},
            )
        assert hidden.status_code == 404
        assert hidden.json()["detail"] == "项目不存在"
        assert (
            json.loads((directory / "regen_budget.json").read_text(encoding="utf-8"))["used"] == 1
        )
        with TestClient(app, headers={"Authorization": f"Bearer {owner.token}"}) as client:
            refused = client.post(
                f"/v1/projects/{project_id}/storyboard/S01",
                json={"voiceover": "先看这台柱塞泵。改过一句"},
            )
        assert refused.status_code == 422
        assert refused.json()["detail"] == REFUSAL
        assert calls == []
        _assert_still_paused(directory, before_script, before_wav)
        from workers.qa.budget_store import open_project_budget

        assert seen
        assert min(seen) == 1
        assert max(seen) == 1
        stored = json.loads((directory / "regen_budget.json").read_text(encoding="utf-8"))
        assert stored["used"] == 1
        assert stored["increase_only"] is True
        assert stored["used"] <= stored["limit"]
        assert open_project_budget(project_id).used == 1
        from workers.workflow.versions import restore_version

        restore_version(project_id, version_id)
        assert open_project_budget(project_id).used == 1
        decoy = json.loads(
            (directory / "versions" / version_id / "regen_budget.json").read_text(encoding="utf-8")
        )
        assert decoy["used"] == 0
        restored = json.loads((directory / "project.json").read_text(encoding="utf-8"))
        assert "regen_used" not in restored
    finally:
        reset_gateway()


def test_narration_edit_refuses_the_pair_before_taking(tmp_path, monkeypatch) -> None:
    """One ``try_take_n(2)``. A pair that does not fit leaves the ledger where it was."""

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "4")
    monkeypatch.setenv("HILATV_LIVE", "0")
    from workers.identity.session import open_session

    owner = open_session()
    project_id = "takefail"
    directory = _hold(project_id, enterprise_id=owner.enterprise_id)
    _seed_budget(directory, 3)
    version_id = _plant_lower_budget(directory)
    calls = _block_generation(monkeypatch)
    from workers.qa.budget_store import ProjectBudget

    real_take_n = ProjectBudget.try_take_n

    def refuse_pair(self: ProjectBudget, count: int) -> bool:
        refuse_pair.calls += 1
        assert count == 2
        return False if count == 2 else real_take_n(self, count)

    refuse_pair.calls = 0
    monkeypatch.setattr(ProjectBudget, "try_take_n", refuse_pair)
    script_path = directory / "nodes" / "n06_voiceover.json"
    before_script = _sha(script_path)
    before_wav = {
        shot_id: _sha(directory / "storyboard" / shot_id / "voice.wav")
        for shot_id in ("S01", "S02")
    }
    from app.main import app
    from gateway.service import reset_gateway

    try:
        with TestClient(app) as anon:
            bare = anon.post(
                f"/v1/projects/{project_id}/storyboard/S01",
                json={"voiceover": "先看这台柱塞泵。改过一句"},
            )
        assert bare.status_code == 401
        assert bare.json()["detail"] == "需要登录"
        stranger = open_session()
        with TestClient(app, headers={"Authorization": f"Bearer {stranger.token}"}) as other:
            hidden = other.post(
                f"/v1/projects/{project_id}/storyboard/S01",
                json={"voiceover": "先看这台柱塞泵。改过一句"},
            )
        assert hidden.status_code == 404
        assert hidden.json()["detail"] == "项目不存在"
        assert refuse_pair.calls == 0
        assert (
            json.loads((directory / "regen_budget.json").read_text(encoding="utf-8"))["used"] == 3
        )
        with TestClient(app, headers={"Authorization": f"Bearer {owner.token}"}) as client:
            refused = client.post(
                f"/v1/projects/{project_id}/storyboard/S01",
                json={"voiceover": "先看这台柱塞泵。改过一句"},
            )
        assert refused.status_code == 422
        assert refused.json()["detail"] == REFUSAL
        assert refuse_pair.calls == 1
        assert calls == []
        _assert_still_paused(directory, before_script, before_wav)
        from workers.qa.budget_store import open_project_budget

        stored = json.loads((directory / "regen_budget.json").read_text(encoding="utf-8"))
        assert stored["used"] == 3
        assert stored["increase_only"] is True
        assert open_project_budget(project_id).used == 3
        from workers.workflow.versions import restore_version

        restore_version(project_id, version_id)
        assert open_project_budget(project_id).used == 3
        decoy = json.loads(
            (directory / "versions" / version_id / "regen_budget.json").read_text(encoding="utf-8")
        )
        assert decoy["used"] == 0
        restored = json.loads((directory / "project.json").read_text(encoding="utf-8"))
        assert "regen_used" not in restored
    finally:
        reset_gateway()


def test_concurrent_narration_edits_charge_the_pair_once(tmp_path, monkeypatch) -> None:
    """A second edit waits on the project lock, sees the flag, and does not charge."""

    import threading

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "12")
    monkeypatch.setenv("HILATV_LIVE", "0")
    directory = _hold("editrace")
    entered = threading.Event()
    release = threading.Event()

    def slow(*_args: object, **_kwargs: object) -> None:
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr("workers.workflow.storyboard._moderate_narration", slow)
    done: dict[str, object] = {}

    def first() -> None:
        try:
            done["body"] = edit_voiceover(
                "editrace",
                "S01",
                "先看这台柱塞泵。改过一句",
                gateway=object(),
            )
        except Exception as exc:
            done["error"] = exc

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(5)
    with pytest.raises(StoryboardError, match="分镜正在保存") as caught:
        edit_voiceover("editrace", "S01", "先看这台柱塞泵。另一句", gateway=object())
    assert caught.value.status == 409
    from workers.qa.budget_store import open_project_budget

    assert open_project_budget("editrace").used == 2
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    stored = json.loads((directory / "regen_budget.json").read_text(encoding="utf-8"))
    assert stored["used"] == 2


def test_exhausted_budget_rejects_before_tts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    gateway = _gateway(tmp_path)
    directory = _hold("nobudget")
    atomic_write(
        directory / "regen_budget.json",
        (json.dumps({"used": 12, "limit": 12, "increase_only": True}) + "\n").encode(),
    )
    script_path = directory / "nodes" / "n06_voiceover.json"
    before_script = _sha(script_path)
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("tts")
        raise AssertionError("tts must not run")

    gateway.tts = forbidden
    with pytest.raises(StoryboardError) as caught:
        edit_voiceover("nobudget", "S01", "先看这台柱塞泵。改过", gateway=gateway)
    assert caught.value.status == 422
    assert calls == []
    assert _sha(script_path) == before_script
    tts_logs = [
        row for row in gateway.store.list_logs(project_id="nobudget") if row["task"] == "tts"
    ]
    assert tts_logs == []


def test_archived_cloned_voice_survives_a_narration_edit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path / "brands"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    from workers.brand_kit.store import BrandRecord, save_record
    from workers.schemas.brand import BrandKit

    gateway = _gateway(tmp_path)
    enterprise_id = "11111111-1111-4111-8111-111111111111"
    raw = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "schemas"
            / "tests"
            / "fixtures"
            / "brand_kit.json"
        ).read_text(encoding="utf-8")
    )
    raw["voice"]["tts_voice"] = "clone-boss-1"
    raw["people"][0]["consent"] = True
    raw["people"][0]["role"] = "老板"
    raw["people"][0]["voice_id"] = "clone-boss-1"
    kit = BrandKit.model_validate(raw).model_dump(mode="json")
    save_record(BrandRecord(enterprise_id=enterprise_id, brand_kit=kit))
    project_id = "clonevoice"
    script = _script("先看这台柱塞泵。", "请来厂里看设备。")
    script["shots"][0]["purpose"] = "人物出镜"
    script["shots"][0]["subject_refs"] = ["person:老板"]
    script["shots"][0]["generation_mode"] = "reference_to_video"
    voice = run_voice(
        {
            "project_id": project_id,
            "payload": {"script": script, "brand_kit": kit, "enterprise_id": enterprise_id},
        },
        gateway=gateway,
    )
    frames = run_frames(
        {
            "project_id": project_id,
            "payload": {
                "script": voice.payload["script"],
                "brand_kit": kit,
                "enterprise_id": enterprise_id,
                "keyframe_candidates": 3,
            },
        },
        gateway=gateway,
    )
    init_project(project_id, sentence="看分镜", skip_storyboard=False, enterprise_id=enterprise_id)
    directory = project_path(project_id)
    _write_node(
        directory,
        "n06_voiceover",
        {
            "script": voice.payload["script"],
            "voiceovers": voice.payload["voiceovers"],
            "brand_kit": kit,
        },
    )
    _write_node(directory, "n08_keyframe", {"keyframes": frames.payload["candidates"]})
    snapshot = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    snapshot["status"] = "paused"
    snapshot["storyboard_gate"] = "hold"
    snapshot["enterprise_id"] = enterprise_id
    atomic_write(
        directory / "project.json",
        (json.dumps(snapshot, ensure_ascii=False) + "\n").encode(),
    )
    edited = "先看这台柱塞泵。档案里的声音还在"
    result = edit_voiceover(project_id, "S01", edited, gateway=gateway)
    assert result["nodes"][0] == "n06_voiceover"
    saved = json.loads((directory / "nodes" / "n06_voiceover.json").read_text(encoding="utf-8"))
    spoken = next(
        shot["voiceover"] for shot in saved["script"]["shots"] if shot["shot_id"] == "S01"
    )
    assert spoken == edited
    assert saved["voiceovers"][0]["voice"] == "clone-boss-1"
