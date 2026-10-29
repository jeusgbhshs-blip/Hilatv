"""Longer dictionary phrases win, and the TTS body carries SSML plus the pause."""

from __future__ import annotations

import base64
import json

import httpx

from gateway.adapters.volc_tts import VolcTtsAdapter, apply_ssml
from gateway.media_bytes import render_wav
from gateway.models import Invocation
from gateway.pricing import Pricing
from gateway.storage import MemoryObjectStore
from workers.nodes.n06_voiceover.lexicon import load_lexicon, matching_terms


def test_longer_phrase_hides_the_shorter_one() -> None:
    hits = matching_terms("这台柱塞泵耐压", load_lexicon())
    assert [item["text"] for item in hits] == ["柱塞泵"]
    assert hits[0]["pinyin"] == "zhu4 sai1 beng4"


def test_tts_request_carries_speed_pause_and_phoneme() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        wav, _stamps, _duration = render_wav("柱塞泵", 1)
        return httpx.Response(
            200,
            json={
                "code": 3000,
                "message": "Success",
                "data": base64.b64encode(wav).decode(),
                "addition": {"duration": "400"},
            },
        )

    adapter = VolcTtsAdapter(
        api_key="token",
        app_id="app-1",
        store=MemoryObjectStore(),
        transport=httpx.MockTransport(handler),
        pricing=Pricing.load(),
    )
    adapter.invoke(
        Invocation(
            task="tts",
            prompt="柱塞泵压力三十兆帕",
            model="seed-tts-1.0",
            provider="volc_tts",
            timeout_s=5,
            params={
                "speed": 1.05,
                "pause_s": 0.4,
                "lexicon": [{"text": "柱塞泵", "pinyin": "zhu4 sai1 beng4"}],
            },
        )
    )
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["audio"]["speed_ratio"] == 1.05
    assert body["request"]["silence_duration"] == 400
    assert body["request"]["text_type"] == "ssml"
    assert body["request"]["with_timestamp"] == 1
    text = body["request"]["text"]
    assert isinstance(text, str)
    assert '<phoneme alphabet="py" ph="zhu4 sai1 beng4">柱塞泵</phoneme>' in text
    plain, kind = apply_ssml("没有术语", [])
    assert kind == "plain"
    assert plain == "没有术语"
