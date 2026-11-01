"""Deterministic adapter used when live calls are off, unkeyed, or over budget."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from decimal import Decimal
from typing import Any

from gateway.aspects import mock_dimensions
from gateway.constants import TASKS
from gateway.errors import AdapterError
from gateway.media_bytes import (
    MOCK_HEIGHT,
    MOCK_WIDTH,
    prosody_timing,
    render_beat_wav,
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
        if call.task == "video" and video_fault(call.shot_id):
            raise AdapterError(f"injected video failure for {call.shot_id or '*'}")
        if call.task in {"matte", "relight"}:
            from gateway.adapters.local_vision import invoke_local

            return AdapterResult(
                provider=self.provider,
                model=call.model or f"mock-{call.task}",
                output=invoke_local(call),
                cost_cny=Decimal("0"),
            )
        if call.json_schema is not None:
            output = fill_json_schema(call.json_schema)
            if not isinstance(output, dict):
                output = {"value": output}
        elif self.store is not None and call.task in {"image", "video", "tts", "music"}:
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
        fields = {
            "mock": True,
            "task": "image",
            "uri": f"mock://image/{digest}",
            "prompt": call.prompt,
            "negative_prompt": call.negative_prompt,
            "seed": call.seed,
        }
        return _attach_bytes(call, fields)
    if call.task == "video":
        fields = {
            "mock": True,
            "task": "video",
            "uri": f"mock://video/{digest}",
            "prompt": call.prompt,
            "negative_prompt": call.negative_prompt,
            "seed": call.seed,
            "duration_s": _video_seconds(call),
        }
        return _attach_bytes(call, fields)
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
        fields = _music_fields(call)
        fields["uri"] = f"mock://music/{digest}"
        return fields
    if call.task == "judge":
        return {
            "mock": True,
            "scores": {"prompt_match": 8, "aesthetics": 8, "artifact_free": 10},
            "hard_fail": [],
            "total": 8.0,
            "evaluator": "mock-judge",
            "notes": "mock",
        }
    if call.task == "content_safety":
        blocked = bool(call.params.get("block")) or "HILATV_UNSAFE_SAMPLE" in call.prompt
        return {
            "mock": True,
            "moderation": "mock",
            "reviewed": False,
            "task": "content_safety",
            "passed": not blocked,
            "labels": ["unsafe"] if blocked else [],
            "manual_review": False,
            "reason": "mock content safety blocked this text" if blocked else "",
            "stage": str(call.params.get("stage") or ""),
        }
    return {"mock": True, "task": call.task, "prompt": call.prompt, "seed": call.seed}


def _stored_media(call: Invocation, store: ObjectStore) -> dict[str, Any]:
    digest = _digest(call)
    width, height = (
        mock_dimensions(call.params)
        if call.task in {"image", "video"}
        else (MOCK_WIDTH, MOCK_HEIGHT)
    )
    if call.task == "image":
        data = render_png(call.seed, width=width, height=height)
        uri = store.put(f"gateway/image/{digest}.png", data, "image/png")
        return _attach_bytes(
            call,
            {
                "mock": True,
                "task": "image",
                "uri": uri,
                "mime_type": "image/png",
                "width": width,
                "height": height,
                "prompt": call.prompt,
                "negative_prompt": call.negative_prompt,
                "seed": call.seed,
            },
        )
    if call.task == "video":
        seconds = _video_seconds(call)
        data = render_mp4(call.seed, duration_s=seconds, width=width, height=height)
        uri = store.put(f"gateway/video/{digest}.mp4", data, "video/mp4")
        return _attach_bytes(
            call,
            {
                "mock": True,
                "task": "video",
                "uri": uri,
                "mime_type": "video/mp4",
                "width": width,
                "height": height,
                "duration_s": seconds,
                "prompt": call.prompt,
                "negative_prompt": call.negative_prompt,
                "seed": call.seed,
            },
        )
    if call.task == "music":
        fields = _music_fields(call)
        duration = _positive(call.params.get("duration_s"), 4.0)
        bpm = _positive(call.params.get("bpm"), 100.0)
        data = render_beat_wav(duration_s=duration, bpm=bpm, seed=call.seed)
        uri = store.put(f"gateway/music/{digest}.wav", data, "audio/wav")
        fields["uri"] = uri
        fields["mime_type"] = "audio/wav"
        fields["duration_s"] = duration
        fields["bpm"] = bpm
        return fields
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


def _music_fields(call: Invocation) -> dict[str, Any]:
    """License and tempo travel with every mock music response.

    The defaults are the in-repo test library (synthesized, CC0). A node that
    picked a catalog row passes that row's source and license through params.
    """

    source = call.params.get("source")
    license_name = call.params.get("license")
    library_id = call.params.get("library_id")
    return {
        "mock": True,
        "task": "music",
        "prompt": call.prompt,
        "duration_s": call.params.get("duration_s"),
        "seed": call.seed,
        "bpm": _positive(call.params.get("bpm"), 100.0),
        "source": source
        if isinstance(source, str) and source.strip()
        else "hilatv-test-library/steady",
        "license": license_name
        if isinstance(license_name, str) and license_name.strip()
        else "CC0-1.0",
        "library_id": library_id
        if isinstance(library_id, str) and library_id.strip()
        else "hilatv-self-made-steady",
        "instrumental": True,
    }


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


def video_fault(shot_id: str | None) -> bool:
    """True when this process is injecting a failed video model for the shot.

    ``HILATV_FAIL_VIDEO_SHOTS`` is empty in normal runs. ``*`` fails every shot.
    """

    raw = os.getenv("HILATV_FAIL_VIDEO_SHOTS", "").strip()
    if not raw:
        return False
    wanted = {item.strip() for item in raw.split(",") if item.strip()}
    if "*" in wanted:
        return True
    return bool(shot_id) and shot_id in wanted


def _attach_bytes(call: Invocation, fields: dict[str, Any]) -> dict[str, Any]:
    """Optional pixels so a caller can write the mock frame into the project."""

    if not call.params.get("materialize"):
        return fields
    width, height = (
        mock_dimensions(call.params)
        if call.task in {"image", "video"}
        else (MOCK_WIDTH, MOCK_HEIGHT)
    )
    if call.task == "image":
        data = render_png(call.seed, width=width, height=height)
        fields["png_b64"] = base64.b64encode(data).decode("ascii")
        fields["width"] = width
        fields["height"] = height
    elif call.task == "video":
        data = render_mp4(call.seed, duration_s=_video_seconds(call), width=width, height=height)
        fields["mp4_b64"] = base64.b64encode(data).decode("ascii")
    return fields


def _digest(call: Invocation) -> str:
    raw = json.dumps(
        {
            "task": call.task,
            "prompt": call.prompt,
            "seed": call.seed,
            "voice": call.params.get("voice"),
            "ratio": call.params.get("ratio"),
            "size": call.params.get("size"),
            "resolution": call.params.get("resolution"),
            "duration_s": call.params.get("duration_s"),
            "speed": call.params.get("speed"),
            "pause_s": call.params.get("pause_s"),
            "bpm": call.params.get("bpm"),
            "library_id": call.params.get("library_id"),
            "language": call.language,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
