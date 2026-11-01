"""Seedream image adapter. HTTP only, via the Volcengine Ark images API.

The current image API is synchronous. `watermark` is forced off so the model
does not burn a logo into the frame. On-screen text is a render-layer concern.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx

from gateway.adapters.http_json import bearer, decode_b64, download_bytes, price_media, request_json
from gateway.constants import ARK_BASE_URL
from gateway.errors import AdapterError
from gateway.image_inputs import image_data_url
from gateway.media_bytes import extension_for, sniff_mime
from gateway.models import AdapterResult, Invocation
from gateway.pricing import Pricing
from gateway.storage import ObjectStore


class SeedreamAdapter:
    provider = "seedream"
    billable = True
    tasks = frozenset({"image"})

    def __init__(
        self,
        *,
        base_url: str = ARK_BASE_URL,
        api_key: str = "",
        key_fn: Callable[[], str] | None = None,
        store: ObjectStore | None = None,
        transport: httpx.BaseTransport | None = None,
        pricing: Pricing | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.key_fn = key_fn
        self.store = store
        self.transport = transport
        self._pricing = pricing

    def available(self) -> bool:
        return bool(self._key().strip())

    def invoke(self, call: Invocation) -> AdapterResult:
        if self.store is None:
            raise AdapterError("object store is not configured")
        key = self._key().strip()
        if not key:
            raise AdapterError("seedream api key is empty")
        timeout = httpx.Timeout(call.timeout_s)
        with httpx.Client(timeout=timeout, transport=self.transport) as client:
            payload = request_json(
                client,
                "POST",
                f"{self.base_url}/images/generations",
                headers=bearer(key),
                body=_body(call, self.store),
                provider=self.provider,
            )
            raw, mime = _image_bytes(client, payload)
        ext = extension_for(mime)
        uri = self.store.put(f"gateway/image/{uuid4().hex}.{ext}", raw, mime)
        usage: dict[str, Any] = {"images": _image_count(payload)}
        cost = price_media(self._pricing_table(), call, usage)
        return AdapterResult(
            provider=self.provider,
            model=call.model,
            output={
                "mock": False,
                "task": "image",
                "uri": uri,
                "mime_type": mime,
                "prompt": call.prompt,
                "negative_prompt": call.negative_prompt,
                "seed": call.seed,
            },
            cost_cny=_decimal(cost),
            usage={"images": int(usage["images"])},
        )

    def _key(self) -> str:
        if self.key_fn is not None:
            return self.key_fn() or ""
        return self.api_key or ""

    def _pricing_table(self) -> Pricing:
        if self._pricing is None:
            self._pricing = Pricing.load()
        return self._pricing


def _body(call: Invocation, store: ObjectStore | None = None) -> dict[str, Any]:
    if call.params.get("image_url") or call.params.get("last_frame_url"):
        raise AdapterError("seedream requires reference_images, not video frame roles")
    # Seedream's documented size modes include "1K". Pixel sizes below ~0.9MP are rejected.
    size = str(call.params.get("size") or "1K")
    body: dict[str, Any] = {
        "model": call.model,
        "prompt": call.prompt,
        "size": size,
        "response_format": "url",
        "sequential_image_generation": "disabled",
        "watermark": False,
    }
    references = call.params.get("reference_images")
    if references:
        if not isinstance(references, list) or len(references) > 14:
            raise AdapterError("seedream supports at most 14 reference images")
        if call.model != "doubao-seedream-4-0-250828":
            raise AdapterError("this seedream model does not support reference images")
        images = [image_data_url(uri, call, store) for uri in references]
        body["image"] = images[0] if len(images) == 1 else images
    return body


def _image_bytes(client: httpx.Client, payload: dict[str, object]) -> tuple[bytes, str]:
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise AdapterError("seedream response missing data")
    item = data[0]
    url = item.get("url")
    encoded = item.get("b64_json")
    if isinstance(url, str) and url:
        raw = download_bytes(client, url, provider="seedream")
    elif isinstance(encoded, str) and encoded:
        raw = decode_b64(encoded)
    else:
        raise AdapterError("seedream response missing image bytes")
    if not raw:
        raise AdapterError("seedream returned an empty image")
    return raw, sniff_mime(raw, "image/jpeg")


def _image_count(payload: dict[str, object]) -> int:
    usage = payload.get("usage")
    if isinstance(usage, dict) and usage.get("generated_images"):
        return max(1, int(usage["generated_images"]))
    data = payload.get("data")
    if isinstance(data, list) and data:
        return len(data)
    return 1


def _decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
