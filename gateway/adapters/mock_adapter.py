"""Deterministic adapter used when live calls are off, unkeyed, or over budget."""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from typing import Any

from gateway.constants import TASKS
from gateway.media_bytes import (
    MOCK_HEIGHT,
    MOCK_WIDTH,
    prosody_timing,
    render_mp4,
    render_png,
    render_wav,
)
from gateway.models import AdapterResult, Invocation
from gateway.schema_util import fill_json_schema
from gateway.storage import ObjectStore


class MockAdapter:
    provider = "mock"
    billable = False
    tasks = TASKS

    def __init__(self, store: ObjectStore | None = None) -> None:
        self.store = store

    def available(self) -> bool:
        return True

    def invoke(self, call: Invocation) -> AdapterResult:
        if call.json_schema is not None:
            output = fill_json_schema(call.json_schema)
            if not isinstance(output, dict):
                output = {"value": output}
        elif self.store is not None and call.task in {"image", "video", "tts"}:
            output = _stored_media(call, self.store)
        else:
            output = _unstructured(call)
        return AdapterResult(
            provider=self.provider,
            model=call.model or f"mock-{call.task}",
            output=output,
            cost_cny=Decimal("0"),
        )


def _unstructured(call: Invocation) -> dict[str, object]:
    digest = _digest(call)
    if call.task == "llm":
        return {"text": call.prompt, "mock": True, "seed": call.seed}
    if call.task == "image":
        return {
            "mock": True,
            "task": "image",
            "uri": f"mock://image/{digest}",
            "prompt": call.prompt,
            "negative_prompt": call.negative_prompt,
            "seed": call.seed,
        }
    if call.task == "video":
        return {
            "mock": True,
            "task": "video",
            "uri": f"mock://video/{digest}",
            "prompt": call.prompt,
            "negative_prompt": call.negative_prompt,
            "seed": call.seed,
            "duration_s": _video_seconds(call),
        }
    if call.task == "tts":
        speed, pause = _prosody(call)
        stamps, duration = prosody_timing(
            call.prompt, speed=speed, pause_s=pause, language=call.language
        )
        return {
            "mock": True,
            "task": "tts",
            "uri": f"mock://tts/{digest}",
            "mime_type": "audio/wav",
            "text": call.prompt,
            "voice": call.params.get("voice"),
            "seed": call.seed,
            "speed": speed,
            "pause_s": pause,
            "duration_s": duration,
            "timestamps": stamps,
        }
    if call.task == "asr":
        reference = call.params.get("reference_text")
        text = reference if isinstance(reference, str) else ""
        return {
            "mock": True,
            "task": "asr",
            "text": text,
            "audio_uri": call.prompt,
            "language": call.language,
        }
    if call.task == "music":
        return {
            "mock": True,
            "task": "music",
            "uri": f"mock://music/{digest}",
            "prompt": call.prompt,
            "duration_s": call.params.get("duration_s"),
            "seed": call.seed,
        }
    if call.task == "judge":
        return {
            "mock": True,
            "scores": {"prompt_match": 8, "aesthetics": 8, "artifact_free": 10},
            "hard_fail": [],
            "total": 8.0,
            "evaluator": "mock-judge",
            "notes": "mock",
        }
    return {"mock": True, "task": call.task, "prompt": call.prompt, "seed": call.seed}


def _stored_media(call: Invocation, store: ObjectStore) -> dict[str, Any]:
    digest = _digest(call)
    if call.task == "image":
        data = render_png(call.seed)
        uri = store.put(f"gateway/image/{digest}.png", data, "image/png")
        return {
            "mock": True,
            "task": "image",
            "uri": uri,
            "mime_type": "image/png",
            "width": MOCK_WIDTH,
            "height": MOCK_HEIGHT,
            "prompt": call.prompt,
            "negative_prompt": call.negative_prompt,
            "seed": call.seed,
        }
    if call.task == "video":
        seconds = _video_seconds(call)
        data = render_mp4(call.seed, duration_s=seconds)
        uri = store.put(f"gateway/video/{digest}.mp4", data, "video/mp4")
        return {
            "mock": True,
            "task": "video",
            "uri": uri,
            "mime_type": "video/mp4",
            "width": MOCK_WIDTH,
            "height": MOCK_HEIGHT,
            "duration_s": seconds,
            "prompt": call.prompt,
            "negative_prompt": call.negative_prompt,
            "seed": call.seed,
        }
    speed, pause = _prosody(call)
    data, stamps, duration = render_wav(
        call.prompt, call.seed, speed=speed, pause_s=pause, language=call.language
    )
    uri = store.put(f"gateway/tts/{digest}.wav", data, "audio/wav")
    return {
        "mock": True,
        "task": "tts",
        "uri": uri,
        "mime_type": "audio/wav",
        "text": call.prompt,
        "voice": call.params.get("voice"),
        "seed": call.seed,
        "speed": speed,
        "pause_s": pause,
        "duration_s": duration,
        "timestamps": stamps,
    }


def _video_seconds(call: Invocation) -> float:
    """Honor the requested length. Callers that omit it keep the 1 second sample."""

    raw = call.params.get("duration_s", 1)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(value) or value <= 0:
        return 1.0
    return min(10.0, value)


def _prosody(call: Invocation) -> tuple[float, float]:
    return _positive(call.params.get("speed"), 1.0), _nonneg(call.params.get("pause_s"), 0.0)


def _positive(value: object, default: float) -> float:
    try:
        number = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _nonneg(value: object, default: float) -> float:
    try:
        number = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _digest(call: Invocation) -> str:
    raw = json.dumps(
        {
            "task": call.task,
            "prompt": call.prompt,
            "seed": call.seed,
            "voice": call.params.get("voice"),
            "duration_s": call.params.get("duration_s"),
            "speed": call.params.get("speed"),
            "pause_s": call.params.get("pause_s"),
            "language": call.language,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
