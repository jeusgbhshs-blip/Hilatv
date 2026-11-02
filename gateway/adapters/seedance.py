"""Seedance video adapter. Submits a task, polls, then stores the MP4.

Status values follow the Ark contents-generations API:
queued, running, succeeded, failed, cancelled, expired.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from gateway.adapters.http_json import (
    bearer,
    billable_postprocess,
    download_bytes,
    error_message,
    price_media,
    request_json,
)
from gateway.aspects import SEEDANCE_NATIVE_RATIOS, ratio_parts
from gateway.constants import ARK_BASE_URL
from gateway.errors import AdapterError
from gateway.image_inputs import image_data_url
from gateway.media_bytes import extension_for, sniff_mime
from gateway.models import AdapterResult, Invocation
from gateway.polling import TaskSnapshot, TaskState, poll_task
from gateway.pricing import Pricing
from gateway.storage import ObjectStore

_QUEUED = {"queued", "pending", "submitted"}
_RUNNING = {"running", "processing"}
_SUCCEEDED = {"succeeded", "success", "completed"}
_FAILED = {"failed", "cancelled", "canceled", "expired"}


class SeedanceAdapter:
    provider = "seedance"
    billable = True
    tasks = frozenset({"video"})

    def __init__(
        self,
        *,
        base_url: str = ARK_BASE_URL,
        api_key: str = "",
        key_fn: Callable[[], str] | None = None,
        store: ObjectStore | None = None,
        transport: httpx.BaseTransport | None = None,
        pricing: Pricing | None = None,
        interval_s: float = 2.0,
        now: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.key_fn = key_fn
        self.store = store
        self.transport = transport
        self._pricing = pricing
        self.interval_s = interval_s
        self.now = now or time.monotonic
        self.sleep = sleep or time.sleep

    def available(self) -> bool:
        return bool(self._key().strip())

    def cost_upper_bound(self, call: Invocation, pricing: Any) -> Decimal | None:
        _provider_ratio(call)
        # Estimate the normalized output without reading/encoding input frames.
        params = {
            "duration_s": _duration(call),
            "resolution": str(call.params.get("resolution") or "720p"),
        }
        return pricing.upper_bound(call.model, call.prompt, task=call.task, params=params)

    def invoke(self, call: Invocation) -> AdapterResult:
        if self.store is None:
            raise AdapterError("object store is not configured")
        key = self._key().strip()
        if not key:
            raise AdapterError("seedance api key is empty")
        per_request = min(30.0, max(1.0, call.timeout_s))
        with httpx.Client(timeout=httpx.Timeout(per_request), transport=self.transport) as client:
            task_id = self._submit(client, call, key)
            snap = poll_task(
                lambda: self._fetch(client, task_id, key),
                timeout_s=call.timeout_s,
                interval_s=self.interval_s,
                now=self.now,
                sleep=self.sleep,
            )
            seconds = snap.duration_s if snap.duration_s is not None else float(_duration(call))
            usage: dict[str, Any] = {"video_seconds": seconds}
            if snap.usage.get("completion_tokens"):
                usage["completion_tokens"] = int(snap.usage["completion_tokens"])
            receipt = AdapterResult(
                provider=self.provider,
                model=call.model,
                output={},
                cost_cny=_decimal(price_media(self._pricing_table(), call, usage)),
                usage={"video_seconds": seconds},
            )
            with billable_postprocess(receipt):
                assert snap.result_url is not None
                raw = download_bytes(client, snap.result_url, provider=self.provider)
                mime = sniff_mime(raw, "video/mp4")
                ext = extension_for(mime)
                uri = self.store.put(f"gateway/video/{uuid4().hex}.{ext}", raw, mime)
                receipt.output = {
                    "mock": False,
                    "task": "video",
                    "uri": uri,
                    "mime_type": mime,
                    "duration_s": seconds,
                    "prompt": call.prompt,
                    "negative_prompt": call.negative_prompt,
                    "seed": call.seed,
                    "requested_ratio": str(call.params.get("ratio") or "16:9"),
                    "provider_ratio": _provider_ratio(call),
                    "reference_fit": "contain",
                }
        return receipt

    def _submit(self, client: httpx.Client, call: Invocation, key: str) -> str:
        payload = request_json(
            client,
            "POST",
            f"{self.base_url}/contents/generations/tasks",
            headers=bearer(key),
            body=_submit_body(call, self.store),
            provider=self.provider,
        )
        task_id = str(payload.get("id") or "")
        if not task_id:
            raise AdapterError("seedance submit missing task id")
        return task_id

    def _fetch(self, client: httpx.Client, task_id: str, key: str) -> TaskSnapshot:
        payload = request_json(
            client,
            "GET",
            f"{self.base_url}/contents/generations/tasks/{quote(task_id, safe='')}",
            headers=bearer(key),
            body=None,
            provider=self.provider,
        )
        return _snapshot(payload)

    def _key(self) -> str:
        if self.key_fn is not None:
            return self.key_fn() or ""
        return self.api_key or ""

    def _pricing_table(self) -> Pricing:
        if self._pricing is None:
            self._pricing = Pricing.load()
        return self._pricing


def _submit_body(call: Invocation, store: ObjectStore | None = None) -> dict[str, Any]:
    if call.params.get("reference_images"):
        raise AdapterError("this seedance adapter supports first/last frames, not reference_images")
    body: dict[str, Any] = {
        "model": call.model,
        "content": [{"type": "text", "text": call.prompt}],
        "resolution": str(call.params.get("resolution") or "720p"),
        "ratio": _provider_ratio(call),
        "duration": _duration(call),
        "camera_fixed": bool(call.params.get("camera_fixed") or False),
        "watermark": False,
    }
    if call.seed is not None:
        body["seed"] = int(call.seed)
    image_url = call.params.get("image_url")
    last_frame = call.params.get("last_frame_url")
    if image_url or last_frame:
        # 1.0/2.x 的 Seedance 模型接受首帧/尾帧角色；2.5 等新模型按官方文档逐步放开。
        if not call.model.startswith(("doubao-seedance-1", "doubao-seedance-2")):
            raise AdapterError("this seedance model does not support first/last frame inputs")
        if call.params.get("image_role", "first_frame") != "first_frame":
            raise AdapterError("this seedance adapter only supports first and last frames")
        if last_frame and (not image_url or "fast" in call.model):
            raise AdapterError("this seedance model does not support these first/last frames")
    if image_url:
        body["content"].append(
            {
                "type": "image_url",
                "image_url": {"url": _frame_url(image_url, call, store)},
                "role": "first_frame",
            }
        )
    if last_frame:
        body["content"].append(
            {
                "type": "image_url",
                "image_url": {"url": _frame_url(last_frame, call, store)},
                "role": "last_frame",
            }
        )
    return body


def _frame_url(uri: object, call: Invocation, store: ObjectStore | None) -> str:
    ratio = str(call.params.get("ratio") or "16:9")
    return image_data_url(
        uri,
        call,
        store,
        min_side=300,
        max_side=6000,
        aspect_range=(0.4, 2.5),
        fit_ratio=None if ratio == "adaptive" else ratio,
    )


def _duration(call: Invocation) -> int:
    raw = call.params.get("duration_s", 5)
    try:
        value = int(round(float(raw)))
    except (TypeError, ValueError):
        value = 5
    return min(10, max(2, value))


def _snapshot(payload: dict[str, object]) -> TaskSnapshot:
    status = str(payload.get("status") or "").strip().lower()
    if status in _QUEUED:
        state = TaskState.QUEUED
    elif status in _RUNNING:
        state = TaskState.RUNNING
    elif status in _SUCCEEDED:
        state = TaskState.SUCCEEDED
    elif status in _FAILED:
        state = TaskState.FAILED
    else:
        raise AdapterError(f"unknown task state: {payload.get('status')}")
    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    url = content.get("video_url") if isinstance(content, dict) else None
    if not isinstance(url, str) or not url:
        raw_url = payload.get("video_url")
        url = raw_url if isinstance(raw_url, str) else None
    duration = payload.get("duration")
    duration_s = float(duration) if isinstance(duration, int | float) else None
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return TaskSnapshot(
        state=state,
        result_url=url,
        error=error_message(payload),
        duration_s=duration_s,
        usage=dict(usage),
    )


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _provider_ratio(call: Invocation) -> str:
    ratio = str(call.params.get("ratio") or "16:9")
    if ratio in SEEDANCE_NATIVE_RATIOS:
        return ratio
    if ratio != "adaptive":
        ratio_parts(ratio)
    # The supported 1.0 I2V route may preserve its first frame with adaptive.
    # Frame normalization binds that actual input to the requested target shape.
    if call.params.get("image_url") and call.model in {
        "doubao-seedance-1-0-pro-250528",
        "doubao-seedance-1-0-pro-fast-251015",
    }:
        return "adaptive"
    raise AdapterError("the selected video ratio requires a supported first-frame input")
