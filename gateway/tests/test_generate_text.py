"""Structured generate_text and the other modality entry points."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, Field

from gateway.constants import NO_RENDERED_TEXT, TASKS
from gateway.router import RouteTable, default_routes_path
from gateway.service import generate_text, reset_gateway
from gateway.tests.conftest import build_gateway, mock_llm_routes


class Brief(BaseModel):
    """SPEC §5.2 shape. The canonical model arrives with T02."""

    brief_id: str
    raw_input: str
    goal: str
    platform: list[str]
    duration_s: int = Field(ge=1, le=600)
    aspect_ratios: list[str]
    languages: list[str] = Field(min_length=1)
    video_type: str
    audience: str
    must_include: list[str]
    style: str
    assumptions: list[str]
    open_questions: list[str]


def test_generate_text_validates_brief_and_writes_log(tmp_path) -> None:
    gateway = build_gateway(tmp_path, routes=mock_llm_routes())
    raw = gateway.generate_text(
        "给我们的柱塞泵做个30秒外贸宣传片，英文",
        schema=Brief,
        seed=7,
        project_id="p1",
        node="n01_brief",
        shot_id="S01",
    )
    brief = Brief.model_validate(raw)
    assert brief.duration_s >= 1
    assert brief.languages
    again = gateway.generate_text(
        "给我们的柱塞泵做个30秒外贸宣传片，英文",
        schema=Brief,
        seed=7,
        project_id="p1",
    )
    assert again == raw
    logs = gateway.store.list_logs()
    row = logs[0]
    assert row["model"] == "mock-llm"
    assert row["params"]["seed"] == 7
    assert row["params"]["schema"] == "Brief"
    assert isinstance(row["latency_ms"], int)
    assert Decimal(row["cost"]) == 0
    assert Decimal(row["cost_cny"]) == 0
    assert row["status"] == "ok"
    assert row["qa_score"] is None
    assert row["project_id"] == "p1"
    assert row["node"] == "n01_brief"


def test_json_schema_dict_is_enforced(tmp_path) -> None:
    gateway = build_gateway(tmp_path, routes=mock_llm_routes())
    schema = {
        "type": "object",
        "required": ["goal", "n"],
        "additionalProperties": False,
        "properties": {
            "goal": {"type": "string", "minLength": 1},
            "n": {"type": "integer", "minimum": 1},
        },
    }
    out = gateway.generate_text("x", schema=schema, seed=1)
    import jsonschema

    jsonschema.validate(out, schema)
    assert out == {"goal": "mock", "n": 1}


def test_modalities_return_mock_payloads(tmp_path) -> None:
    gateway = build_gateway(tmp_path, routes=mock_llm_routes())
    image = gateway.generate_image("产品特写", seed=3, shot_type="close_up")
    video = gateway.generate_video("产品旋转", seed=3)
    speech = gateway.tts("三十兆帕", voice="zh_male_steady", seed=3)
    transcript = gateway.asr("oss://clip.wav", language="zh")
    track = gateway.music("稳重工业", duration_s=12, seed=3)
    review = gateway.judge("这个镜头合格吗", seed=3)
    assert image["mock"] is True and image["negative_prompt"] == NO_RENDERED_TEXT
    assert "no text" in image["prompt"] and "电话" in image["prompt"]
    assert video["task"] == "video" and "电话" in video["negative_prompt"]
    assert speech["voice"] == "zh_male_steady" and speech["uri"].startswith("mock://tts/")
    assert transcript["audio_uri"] == "oss://clip.wav"
    assert track["duration_s"] == 12
    assert review["evaluator"] == "mock-judge"
    logged = {row["task"] for row in gateway.store.list_logs()}
    assert logged == {"image", "video", "tts", "asr", "music", "judge"}
    image_log = gateway.store.list_logs()[0]
    assert "no text" in image_log["params"]["prompt"]


def test_packaged_routes_cover_every_task() -> None:
    table = RouteTable(default_routes_path())
    for task in TASKS:
        route = table.resolve(task, None, None)
        assert route.task == task
    assert table.resolve("llm", "close_up", "en").id == "llm-close-up-en"
    assert table.resolve("llm", "wide", "zh").id == "llm-default"
    assert table.resolve("image", None, None).primary.provider == "seedream"
    assert table.resolve("video", None, None).primary.provider == "seedance"
    assert table.resolve("tts", None, None).primary.provider == "volc_tts"
    for task in ("image", "video", "tts"):
        assert table.resolve(task, None, None).fallbacks[-1].provider == "mock"


def test_module_entrypoint_stays_on_mock_without_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv("HILATV_LIVE", "1")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "10")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "10")
    monkeypatch.setenv("HILATV_GATEWAY_STORE", "sqlite")
    monkeypatch.setenv("HILATV_SQLITE_PATH", str(tmp_path / "mod.sqlite"))
    monkeypatch.setenv("HILATV_PROGRESS_PATH", str(tmp_path / "progress.md"))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("ARK_API_KEY", "")
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_gateway()
    try:
        out = generate_text("hello", seed=1)
    finally:
        reset_gateway()
    assert out["mock"] is True
    assert out["text"] == "hello"
    assert not (tmp_path / "progress.md").exists() or "budget_exceeded" not in (
        tmp_path / "progress.md"
    ).read_text(encoding="utf-8")
