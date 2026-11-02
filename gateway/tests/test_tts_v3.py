"""V3 单向流式适配器：逐行 JSON、base64 音频拼接、PCM 包 WAV。"""
import base64
import json
import wave

import httpx

from gateway.adapters.volc_tts import VolcTtsV3Adapter
from gateway.models import Invocation
from gateway.storage import MemoryObjectStore


def _call() -> Invocation:
    return Invocation(
        task="tts",
        prompt="你好，这是一段配音。",
        model="seed-tts-1.0",
        provider="volc_tts_v3",
        params={"voice": "zh_female_vv_uranus_bigtts", "pause_s": 0.1},
        timeout_s=10,
        project_id="p1",
        node="n06_voiceover",
    )


def test_v3_parses_stream_and_wraps_pcm():
    pcm = b"\x00\x01" * 2400
    lines = [
        json.dumps({"code": 0, "message": "", "data": base64.b64encode(pcm[:2400]).decode()}),
        json.dumps(
            {
                "code": 0,
                "message": "",
                "data": base64.b64encode(pcm[2400:]).decode(),
                "sentence": {
                    "text": "你好",
                    "words": [{"word": "你好", "startTime": 0.1, "endTime": 0.4, "confidence": 0.9}],
                },
            }
        ),
        json.dumps({"code": 20000000, "message": "ok", "data": None, "usage": {"text_words": 10}}),
    ]
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=("\n".join(lines) + "\n").encode())

    store = MemoryObjectStore()
    adapter = VolcTtsV3Adapter(
        key_fn=lambda: "test-key",
        speaker_fn=lambda: "zh_female_vv_uranus_bigtts",
        store=store,
        transport=httpx.MockTransport(handler),
    )
    result = adapter.invoke(_call())
    audio = store.get(result.output["uri"])
    with wave.open(__import__("io").BytesIO(audio), "rb") as handle:
        assert handle.getframerate() == 24000
        # 音频长度 = 最后一个字的时间戳(0.4s) + pause_s(0.1s)
        assert handle.getnframes() == 12000
        assert result.output["duration_s"] == 0.5
    assert result.output["mock"] is False
    assert result.output["timestamps"] == [{"text": "你好", "start_s": 0.1, "end_s": 0.4}]
    assert seen["headers"]["X-Api-Key"] == "test-key"
    assert seen["headers"]["X-Api-Resource-Id"] == "seed-tts-2.0"
    body = seen["body"]
    assert body["req_params"]["speaker"] == "zh_female_vv_uranus_bigtts"
    assert body["req_params"]["audio_params"]["format"] == "pcm"
