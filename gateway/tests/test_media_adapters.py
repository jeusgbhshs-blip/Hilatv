"""Image, video, and TTS adapters: store, poll, timestamps, budget, and cost."""

from __future__ import annotations

import base64
import json
from decimal import Decimal

import httpx
import pytest

from gateway.adapters.mock_adapter import MockAdapter
from gateway.adapters.seedance import SeedanceAdapter, _snapshot
from gateway.adapters.seedream import SeedreamAdapter
from gateway.adapters.volc_tts import VolcTtsAdapter, parse_timestamps
from gateway.constants import NO_RENDERED_TEXT
from gateway.errors import AdapterError, AdapterTimeout
from gateway.media_bytes import decode_png, render_png, render_wav
from gateway.models import Invocation
from gateway.polling import TaskState
from gateway.pricing import Pricing
from gateway.registry import build_registry
from gateway.storage import MemoryObjectStore
from gateway.tests.conftest import build_gateway

IMAGE_MODEL = "doubao-seedream-4-0-250828"
VIDEO_MODEL = "doubao-seedance-1-0-pro-250528"
TTS_MODEL = "seed-tts-1.0"

MEDIA_ROUTES = f"""
version: 1
defaults:
  timeout_s: 5
routes:
  - id: image
    task: image
    shot_type: "*"
    language: "*"
    primary: {{provider: seedream, model: {IMAGE_MODEL}}}
    fallbacks:
      - {{provider: mock, model: mock-image}}
  - id: video
    task: video
    shot_type: "*"
    language: "*"
    timeout_s: 5
    primary: {{provider: seedance, model: {VIDEO_MODEL}}}
    fallbacks:
      - {{provider: mock, model: mock-video}}
  - id: tts
    task: tts
    shot_type: "*"
    language: "*"
    primary: {{provider: volc_tts, model: {TTS_MODEL}}}
    fallbacks:
      - {{provider: mock, model: mock-tts}}
"""


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


def test_mock_samples_roundtrip_through_the_store(tmp_path) -> None:
    store = MemoryObjectStore()
    gateway = build_gateway(
        tmp_path,
        routes=MEDIA_ROUTES,
        registry={"mock": MockAdapter(store=store)},
    )
    image = gateway.generate_image("冷色调金属柱塞泵特写", seed=4)
    video = gateway.generate_video("金属柱塞泵缓慢旋转", seed=4, duration_s=5)
    from workers.compliance.consent_gate import issue_tts_consent

    speech = gateway.tts(
        "三十兆帕",
        voice="zh_male_steady",
        seed=4,
        consent_token=issue_tts_consent("zh_male_steady", None),
    )
    assert image["uri"].startswith("oss://hilatv/gateway/image/")
    assert video["uri"].startswith("oss://hilatv/gateway/video/")
    assert speech["uri"].startswith("oss://hilatv/gateway/tts/")
    assert image["negative_prompt"] == NO_RENDERED_TEXT
    width, height, _rgb = decode_png(store.get(image["uri"]))
    assert (width, height) == (320, 180)
    assert store.get(video["uri"])[4:8] == b"ftyp"
    assert speech["voice"] == "zh_male_steady"
    assert [item["text"] for item in speech["timestamps"]] == ["三", "十", "兆", "帕"]
    assert gateway.store.list_logs()[0]["provider"] == "mock"
    assert Decimal(gateway.store.list_logs()[0]["cost_cny"]) == 0
    again = gateway.generate_image("冷色调金属柱塞泵特写", seed=4)
    assert again["uri"] == image["uri"]
    assert gateway.store.list_logs()[-1]["status"] == "cache_hit"


def test_budget_fallback_covers_image_video_and_tts(tmp_path) -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"live call should not run: {request.url}")

    transport = httpx.MockTransport(explode)
    registry = {
        "seedream": SeedreamAdapter(api_key="k", store=MemoryObjectStore(), transport=transport),
        "seedance": SeedanceAdapter(api_key="k", store=MemoryObjectStore(), transport=transport),
        "volc_tts": VolcTtsAdapter(
            api_key="k",
            app_id="app",
            store=MemoryObjectStore(),
            transport=transport,
        ),
    }
    gateway = build_gateway(
        tmp_path,
        routes=MEDIA_ROUTES,
        registry=registry,
        limits=(True, Decimal("0"), Decimal("0")),
        pricing=Pricing.load(),
    )
    image = gateway.generate_image("泵", seed=1)
    video = gateway.generate_video("泵旋转", seed=1)
    from workers.compliance.consent_gate import issue_tts_consent

    speech = gateway.tts(
        "稳定工作",
        voice="zh_male_steady",
        seed=1,
        consent_token=issue_tts_consent("zh_male_steady", None),
    )
    assert image["mock"] is True and video["mock"] is True and speech["mock"] is True
    logs = gateway.store.list_logs()
    assert {row["task"] for row in logs} == {"image", "video", "tts"}
    assert {row["fallback_reason"] for row in logs} == {"budget_exceeded"}
    assert {Decimal(row["cost_cny"]) for row in logs} == {Decimal("0")}
    assert gateway.store.list_alerts()


def test_seedream_stores_bytes_and_records_cost(tmp_path) -> None:
    png = render_png(2)
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "data": [{"b64_json": base64.b64encode(png).decode()}],
                "usage": {"generated_images": 1},
            },
        )

    store = MemoryObjectStore()
    gateway = build_gateway(
        tmp_path,
        routes=MEDIA_ROUTES,
        registry={
            "seedream": SeedreamAdapter(
                api_key="k",
                store=store,
                transport=httpx.MockTransport(handler),
                pricing=Pricing.load(),
            )
        },
        limits=(True, Decimal("10"), Decimal("10")),
        pricing=Pricing.load(),
    )
    out = gateway.generate_image("金属泵体", seed=2, project_id="p")
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["watermark"] is False
    assert body["model"] == IMAGE_MODEL
    assert "seed" not in body
    assert "no text" in body["prompt"] and "电话" in body["prompt"]
    assert out["mock"] is False
    assert out["uri"].startswith("oss://")
    assert store.get(out["uri"]) == png
    row = gateway.store.list_logs()[-1]
    assert row["live"] in {1, True}
    assert Decimal(row["cost_cny"]) == Decimal("0.200000")
    assert row["provider"] == "seedream"


def test_seedream_downloads_a_url(tmp_path) -> None:
    png = render_png(9)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=png)
        return httpx.Response(200, json={"data": [{"url": "https://cdn.example/frame.png"}]})

    store = MemoryObjectStore()
    adapter = SeedreamAdapter(
        api_key="k",
        store=store,
        transport=httpx.MockTransport(handler),
        pricing=Pricing.load(),
    )
    result = adapter.invoke(
        Invocation(
            task="image",
            prompt="金属泵体",
            model=IMAGE_MODEL,
            provider="seedream",
            timeout_s=5,
        )
    )
    assert store.get(str(result.output["uri"])) == png
    assert result.cost_cny == Decimal("0.200000")


def test_seedance_polls_then_stores(tmp_path) -> None:
    clock = Clock()
    gets = {"n": 0}
    mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 8

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content.decode())
            assert body["watermark"] is False
            assert body["duration"] == 5
            assert body["seed"] == 11
            assert "no text" in body["content"][0]["text"]
            return httpx.Response(200, json={"id": "cgt-1"})
        if request.url.host == "cdn.example":
            return httpx.Response(200, content=mp4)
        gets["n"] += 1
        status = {1: "queued", 2: "running"}.get(gets["n"], "succeeded")
        payload: dict[str, object] = {"id": "cgt-1", "status": status}
        if status == "succeeded":
            payload["duration"] = 5
            payload["content"] = {"video_url": "https://cdn.example/clip.mp4"}
            payload["usage"] = {"completion_tokens": 100}
        return httpx.Response(200, json=payload)

    store = MemoryObjectStore()
    gateway = build_gateway(
        tmp_path,
        routes=MEDIA_ROUTES,
        registry={
            "seedance": SeedanceAdapter(
                api_key="k",
                store=store,
                transport=httpx.MockTransport(handler),
                pricing=Pricing.load(),
                interval_s=2,
                now=clock.now,
                sleep=clock.sleep,
            )
        },
        limits=(True, Decimal("20"), Decimal("20")),
        pricing=Pricing.load(),
    )
    out = gateway.generate_video("泵旋转", seed=11, duration_s=5)
    assert gets["n"] == 3
    assert clock.t == 4
    assert out["mock"] is False
    assert store.get(out["uri"]) == mp4
    assert Decimal(gateway.store.list_logs()[-1]["cost_cny"]) == Decimal("2.500000")


def test_seedance_failure_and_timeout(tmp_path) -> None:
    def failed(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "cgt-fail"})
        return httpx.Response(
            200,
            json={"id": "cgt-fail", "status": "failed", "error": {"message": "rejected"}},
        )

    clock = Clock()
    store = MemoryObjectStore()
    adapter = SeedanceAdapter(
        api_key="k",
        store=store,
        transport=httpx.MockTransport(failed),
        interval_s=1,
        now=clock.now,
        sleep=clock.sleep,
    )
    with pytest.raises(AdapterError, match="rejected"):
        adapter.invoke(_video_call())

    def stuck(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"id": "cgt-wait"})
        return httpx.Response(200, json={"id": "cgt-wait", "status": "queued"})

    clock = Clock()
    waiting = SeedanceAdapter(
        api_key="k",
        store=store,
        transport=httpx.MockTransport(stuck),
        interval_s=2,
        now=clock.now,
        sleep=clock.sleep,
    )
    with pytest.raises(AdapterTimeout):
        waiting.invoke(_video_call())
    assert clock.t >= 5


def test_unknown_vendor_status_is_rejected() -> None:
    with pytest.raises(AdapterError, match="unknown task state"):
        _snapshot({"status": "mystery"})
    snap = _snapshot({"status": "cancelled", "error": {"message": "stopped"}})
    assert snap.state == TaskState.FAILED
    assert snap.error == "stopped"


def test_tts_returns_audio_and_word_timestamps(tmp_path) -> None:
    wav, _stamps, _duration = render_wav("三十", 1)
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content.decode())
        frontend = {
            "words": [
                {"word": "三", "start_time": 0, "end_time": 200},
                {"word": "十", "start_time": 200, "end_time": 400},
            ]
        }
        return httpx.Response(
            200,
            json={
                "code": 3000,
                "message": "Success",
                "data": base64.b64encode(wav).decode(),
                "addition": {"duration": "400", "frontend": json.dumps(frontend)},
            },
        )

    store = MemoryObjectStore()
    gateway = build_gateway(
        tmp_path,
        routes=MEDIA_ROUTES,
        registry={
            "volc_tts": VolcTtsAdapter(
                api_key="token",
                app_id="app-1",
                store=store,
                transport=httpx.MockTransport(handler),
                pricing=Pricing.load(),
            )
        },
        limits=(True, Decimal("10"), Decimal("10")),
        pricing=Pricing.load(),
    )
    from workers.compliance.consent_gate import issue_tts_consent

    out = gateway.tts(
        "三十",
        voice="zh_male_steady",
        seed=1,
        consent_token=issue_tts_consent("zh_male_steady", None),
    )
    body = seen["body"]
    assert isinstance(body, dict)
    assert str(seen["auth"]).startswith("Bearer;")
    assert body["request"]["with_timestamp"] == 1
    assert body["audio"]["voice_type"] != "zh_male_steady"
    assert body["audio"]["encoding"] == "wav"
    assert out["voice"] == "zh_male_steady"
    assert out["timestamps"] == [
        {"text": "三", "start_s": 0.0, "end_s": 0.2},
        {"text": "十", "start_s": 0.2, "end_s": 0.4},
    ]
    assert store.get(out["uri"]) == wav
    # 2 characters * ¥2 / 1000
    assert Decimal(gateway.store.list_logs()[-1]["cost_cny"]) == Decimal("0.004000")


def test_tts_timestamp_parser_keeps_second_scale() -> None:
    stamps = parse_timestamps({"words": [{"text": "泵", "startTime": 0.1, "endTime": 0.4}]})
    assert stamps == [{"text": "泵", "start_s": 0.1, "end_s": 0.4}]


def test_vendor_error_falls_back_to_stored_mock(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    store = MemoryObjectStore()
    gateway = build_gateway(
        tmp_path,
        routes=MEDIA_ROUTES,
        registry={
            "mock": MockAdapter(store=store),
            "seedream": SeedreamAdapter(
                api_key="k",
                store=store,
                transport=httpx.MockTransport(handler),
            ),
        },
        limits=(True, Decimal("10"), Decimal("10")),
    )
    out = gateway.generate_image("金属泵体", seed=3)
    assert out["mock"] is True
    assert out["uri"].startswith("oss://")
    decode_png(store.get(out["uri"]))
    assert [row["status"] for row in gateway.store.list_logs()] == ["error", "ok"]


def test_registry_media_adapters_stay_off_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ARK_API_KEY",
        "SEEDREAM_API_KEY",
        "SEEDANCE_API_KEY",
        "VOLC_TTS_API_KEY",
        "VOLC_TTS_APP_ID",
        "VOLC_ASR_API_KEY",
        "VOLC_ASR_APP_ID",
    ):
        monkeypatch.setenv(name, "")
    registry = build_registry(store=MemoryObjectStore())
    assert registry["seedream"].available() is False
    assert registry["seedance"].available() is False
    assert registry["volc_tts"].available() is False
    assert registry["volc_asr"].available() is False
    monkeypatch.setenv("ARK_API_KEY", "ark")
    monkeypatch.setenv("VOLC_TTS_API_KEY", "tok")
    monkeypatch.setenv("VOLC_TTS_APP_ID", "app")
    registry = build_registry(store=MemoryObjectStore())
    assert registry["seedream"].available() is True
    assert registry["seedance"].available() is True
    assert registry["volc_tts"].available() is True
    assert registry["volc_asr"].available() is False
    monkeypatch.setenv("VOLC_ASR_API_KEY", "asr-tok")
    monkeypatch.setenv("VOLC_ASR_APP_ID", "asr-app")
    registry = build_registry(store=MemoryObjectStore())
    assert registry["volc_asr"].available() is True


def test_media_price_table() -> None:
    pricing = Pricing.load()
    assert pricing.estimate(IMAGE_MODEL, "泵", task="image") == Decimal("0.200000")
    assert pricing.estimate(VIDEO_MODEL, "泵", task="video", params={"duration_s": 4}) == Decimal(
        "2.000000"
    )
    assert pricing.estimate(TTS_MODEL, "三十", task="tts") == Decimal("0.004000")
    assert pricing.estimate("ep-custom", "泵", task="image") == Decimal("0.200000")


def _video_call() -> Invocation:
    return Invocation(
        task="video",
        prompt=f"泵旋转\n\nNegative: {NO_RENDERED_TEXT}",
        model=VIDEO_MODEL,
        provider="seedance",
        timeout_s=5,
        seed=11,
        negative_prompt=NO_RENDERED_TEXT,
        params={"duration_s": 5},
    )
