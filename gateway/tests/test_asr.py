"""Volcengine flash ASR: one HTTP call, transcript in, no reference text leaked."""

from __future__ import annotations

import base64
import json
from decimal import Decimal

import httpx

from gateway.adapters.volc_asr import VolcAsrAdapter, parse_transcript
from gateway.media_bytes import render_wav
from gateway.pricing import Pricing
from gateway.storage import MemoryObjectStore
from gateway.tests.conftest import build_gateway

ASR_MODEL = "volc-asr-1.0"
ASR_ROUTES = f"""
version: 1
defaults:
  timeout_s: 5
routes:
  - id: asr
    task: asr
    shot_type: "*"
    language: "*"
    primary: {{provider: volc_asr, model: {ASR_MODEL}}}
    fallbacks:
      - {{provider: mock, model: mock-asr}}
"""


def test_flash_asr_posts_audio_and_returns_text(tmp_path) -> None:
    wav, _stamps, duration = render_wav("三十", 1)
    store = MemoryObjectStore()
    uri = store.put("gateway/tts/sample.wav", wav, "audio/wav")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["app"] = request.headers["x-api-app-key"]
        seen["resource"] = request.headers["x-api-resource-id"]
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"result": {"text": "三十"}})

    gateway = build_gateway(
        tmp_path,
        routes=ASR_ROUTES,
        registry={
            "volc_asr": VolcAsrAdapter(
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
    out = gateway.asr(uri, language="zh", params={"reference_text": "三十"})
    body = seen["body"]
    assert isinstance(body, dict)
    assert seen["app"] == "app-1"
    assert seen["resource"] == "volc.bigasr.auc_turbo"
    assert body["audio"]["data"] == base64.b64encode(wav).decode("ascii")
    assert "reference_text" not in body
    assert out["text"] == "三十"
    assert out["mock"] is False
    # 0.4s * ¥0.004
    assert duration == 0.4
    assert Decimal(gateway.store.list_logs()[-1]["cost_cny"]) == Decimal("0.001600")


def test_parse_transcript_reads_a_result_list() -> None:
    assert parse_transcript({"result": [{"text": "泵"}]}) == "泵"
