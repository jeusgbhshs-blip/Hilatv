"""Doubao / Volcengine one-shot ASR over the HTTP flash recognize API.

The audio URI is downloaded from object storage and posted as base64. A
``reference_text`` param is ignored here: it exists so the mock adapter can
exercise the character-error check when no ASR key is configured.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx

from gateway.adapters.http_json import billable_postprocess, price_media, request_json
from gateway.constants import VOLC_ASR_BASE_URL, VOLC_ASR_FLASH_PATH, VOLC_ASR_RESOURCE
from gateway.errors import AdapterError
from gateway.media_bytes import decode_wav, sniff_mime
from gateway.models import AdapterResult, Invocation
from gateway.pricing import Pricing
from gateway.storage import ObjectStore


class VolcAsrAdapter:
    provider = "volc_asr"
    billable = True
    tasks = frozenset({"asr"})

    def __init__(
        self,
        *,
        base_url: str = VOLC_ASR_BASE_URL,
        api_key: str = "",
        app_id: str = "",
        resource_id: str = VOLC_ASR_RESOURCE,
        key_fn: Callable[[], str] | None = None,
        app_id_fn: Callable[[], str] | None = None,
        store: ObjectStore | None = None,
        transport: httpx.BaseTransport | None = None,
        pricing: Pricing | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.app_id = app_id
        self.resource_id = resource_id or VOLC_ASR_RESOURCE
        self.key_fn = key_fn
        self.app_id_fn = app_id_fn
        self.store = store
        self.transport = transport
        self._pricing = pricing

    def available(self) -> bool:
        return bool(self._key().strip() and self._app_id().strip())

    def cost_upper_bound(self, call: Invocation, pricing: Any) -> Decimal | None:
        if self.store is None:
            return None
        try:
            seconds = decode_wav(self.store.get(call.prompt.strip()))
        except Exception:
            return None
        return pricing.upper_bound(
            call.model,
            call.prompt,
            task="asr",
            params={"_decoded_audio_seconds": seconds},
        )

    def invoke(self, call: Invocation) -> AdapterResult:
        if self.store is None:
            raise AdapterError("object store is not configured")
        token = self._key().strip()
        app_id = self._app_id().strip()
        if not token or not app_id:
            raise AdapterError("volc asr app id or access token is empty")
        uri = call.prompt.strip()
        if not uri:
            raise AdapterError("asr audio uri is empty")
        raw = self.store.get(uri)
        if not raw:
            raise AdapterError("asr audio is empty")
        audio_format = "wav" if sniff_mime(raw, "audio/wav") == "audio/wav" else "mp3"
        timeout = httpx.Timeout(call.timeout_s)
        with httpx.Client(timeout=timeout, transport=self.transport) as client:
            payload = request_json(
                client,
                "POST",
                f"{self.base_url}{VOLC_ASR_FLASH_PATH}",
                headers={
                    "X-Api-App-Key": app_id,
                    "X-Api-Access-Key": token,
                    "X-Api-Resource-Id": self.resource_id,
                    "X-Api-Request-Id": uuid4().hex,
                    "X-Api-Sequence": "-1",
                    "Content-Type": "application/json",
                },
                body={
                    "user": {"uid": call.project_id or "hilatv"},
                    "audio": {
                        "data": base64.b64encode(raw).decode("ascii"),
                        "format": audio_format,
                    },
                    "request": {"model_name": "bigmodel"},
                },
                provider=self.provider,
            )
        try:
            seconds = round(decode_wav(raw), 3) if audio_format == "wav" else 0.0
        except AdapterError:
            seconds = 0.0
        usage = {"audio_seconds": seconds or 1.0}
        cost = price_media(self._pricing_table(), call, usage)
        receipt = AdapterResult(
            provider=self.provider,
            model=call.model,
            output={},
            cost_cny=_decimal(cost),
            usage=usage,
        )
        with billable_postprocess(receipt):
            receipt.output = {
                "mock": False,
                "task": "asr",
                "text": parse_transcript(payload),
                "audio_uri": uri,
                "language": call.language,
            }
        return receipt

    def _key(self) -> str:
        if self.key_fn is not None:
            return self.key_fn() or ""
        return self.api_key or ""

    def _app_id(self) -> str:
        if self.app_id_fn is not None:
            return self.app_id_fn() or ""
        return self.app_id or ""

    def _pricing_table(self) -> Pricing:
        if self._pricing is None:
            self._pricing = Pricing.load()
        return self._pricing


def parse_transcript(payload: dict[str, Any]) -> str:
    code = payload.get("code")
    result = payload.get("result")
    text = _text_of(result)
    if text is None and isinstance(payload.get("text"), str):
        text = payload["text"]
    if text is None:
        if code is not None and str(code) not in {"0", "1000", "20000000"}:
            message = payload.get("message") or code
            raise AdapterError(f"volc asr failed: {message}")
        raise AdapterError("volc asr response missing text")
    return text


def _text_of(result: object) -> str | None:
    if isinstance(result, dict):
        text = result.get("text")
        if isinstance(text, str):
            return text
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict) and isinstance(first.get("text"), str):
            return str(first["text"])
    return None


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
