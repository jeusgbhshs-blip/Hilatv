"""Content-safety HTTP adapter. No vendor SDK.

推断: the request body is ``{"text", "stage"}`` and the JSON response has
``passed``, ``labels``, and ``reason``. The vendor and URL are not chosen yet.
Leave ``CONTENT_SAFETY_API_KEY`` and ``CONTENT_SAFETY_BASE_URL`` empty to stay
on the mock adapter. A live call also needs ``HILATV_LIVE=1`` and a budget.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from gateway.adapters.http_json import bearer, request_json
from gateway.errors import AdapterError
from gateway.models import AdapterResult, Invocation


class ContentSafetyAdapter:
    provider = "content_safety"
    billable = True
    tasks = frozenset({"content_safety"})

    def __init__(
        self,
        *,
        base_url: str = "",
        key_fn: Callable[[], str] | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.key_fn = key_fn or (lambda: os.getenv("CONTENT_SAFETY_API_KEY", ""))
        self.transport = transport

    def available(self) -> bool:
        return bool(self.key_fn().strip() and self.base_url)

    def invoke(self, call: Invocation) -> AdapterResult:
        key = self.key_fn().strip()
        if not key or not self.base_url:
            raise AdapterError("content safety key is not configured")
        body = {
            "text": call.prompt,
            "stage": str(call.params.get("stage") or "input"),
        }
        timeout = httpx.Timeout(call.timeout_s)
        with httpx.Client(timeout=timeout, transport=self.transport, trust_env=False) as client:
            payload = request_json(
                client,
                "POST",
                f"{self.base_url}/moderate",
                headers=bearer(key),
                body=body,
                provider=self.provider,
            )
        if not isinstance(payload.get("passed"), bool):
            raise AdapterError("content safety response has no passed flag")
        labels = payload.get("labels") if isinstance(payload.get("labels"), list) else []
        output: dict[str, Any] = {
            "mock": False,
            "moderation": "live",
            "reviewed": True,
            "passed": payload["passed"],
            "labels": [str(item) for item in labels],
            "reason": str(payload.get("reason") or ""),
            "stage": body["stage"],
            "manual_review": bool(payload.get("manual_review")),
        }
        return AdapterResult(
            provider=self.provider,
            model=call.model or "content-security",
            output=output,
            cost_cny=Decimal("0"),
        )
