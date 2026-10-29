"""Shared HTTP helpers for vendor adapters. Responses stay inside the gateway."""

from __future__ import annotations

import base64

import httpx

from gateway.errors import AdapterError, AdapterTimeout
from gateway.models import Invocation
from gateway.pricing import Pricing


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, object] | None,
    provider: str,
) -> dict[str, object]:
    try:
        response = client.request(method, url, headers=headers, json=body)
    except httpx.TimeoutException as exc:
        raise AdapterTimeout(f"{provider} timeout") from exc
    except httpx.HTTPError as exc:
        raise AdapterError(f"{provider} request failed") from exc
    if response.status_code >= 400:
        raise AdapterError(f"{provider} HTTP {response.status_code}: {response.text[:300]}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise AdapterError(f"{provider} returned non-JSON") from exc
    if not isinstance(payload, dict):
        raise AdapterError(f"{provider} returned a non-object")
    return payload


def download_bytes(client: httpx.Client, url: str, *, provider: str) -> bytes:
    try:
        response = client.get(url)
    except httpx.TimeoutException as exc:
        raise AdapterTimeout(f"{provider} download timeout") from exc
    except httpx.HTTPError as exc:
        raise AdapterError(f"{provider} download failed") from exc
    if response.status_code >= 400 or not response.content:
        raise AdapterError(f"{provider} download HTTP {response.status_code}")
    return response.content


def decode_b64(value: str) -> bytes:
    text = value.strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=False)
    except (ValueError, TypeError) as exc:
        raise AdapterError("vendor returned invalid base64") from exc


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def price_media(pricing: Pricing, call: Invocation, usage: dict[str, object]) -> object:
    from decimal import Decimal

    from gateway.money import money

    cost = pricing.from_usage(call.model, usage)
    if cost:
        return cost
    params = dict(call.params)
    if "video_seconds" in usage and "duration_s" not in params:
        params["duration_s"] = usage["video_seconds"]
    return money(
        pricing.estimate(
            call.model,
            call.prompt,
            task=call.task,
            params=params,
        )
        or Decimal("0")
    )


def error_message(payload: dict[str, object]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code")
        if message:
            return str(message)
    if isinstance(error, str) and error:
        return error
    message = payload.get("message")
    if message and str(payload.get("code") or "") not in {"", "3000", "0"}:
        return str(message)
    return ""
