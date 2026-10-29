"""Deterministic adapter used when live calls are off, unkeyed, or over budget."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from gateway.constants import TASKS
from gateway.models import AdapterResult, Invocation
from gateway.schema_util import fill_json_schema


class MockAdapter:
    provider = "mock"
    billable = False
    tasks = TASKS

    def available(self) -> bool:
        return True

    def invoke(self, call: Invocation) -> AdapterResult:
        if call.json_schema is not None:
            output = fill_json_schema(call.json_schema)
            if not isinstance(output, dict):
                output = {"value": output}
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
        }
    if call.task == "tts":
        return {
            "mock": True,
            "task": "tts",
            "uri": f"mock://tts/{digest}",
            "text": call.prompt,
            "voice": call.params.get("voice"),
            "seed": call.seed,
        }
    if call.task == "asr":
        return {
            "mock": True,
            "task": "asr",
            "text": "",
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


def _digest(call: Invocation) -> str:
    raw = json.dumps(
        {"task": call.task, "prompt": call.prompt, "seed": call.seed},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
