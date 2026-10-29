"""OpenAI-compatible HTTP chat adapter. No vendor SDK."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from gateway.errors import AdapterError, AdapterTimeout
from gateway.models import AdapterResult, Invocation

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class OpenAICompatAdapter:
    """DeepSeek, DashScope compatible-mode, and Volcengine Ark share this client."""

    billable = True

    def __init__(
        self,
        *,
        provider: str,
        api_key: str = "",
        base_url: str,
        key_fn: Callable[[], str] | None = None,
        transport: httpx.BaseTransport | None = None,
        tasks: frozenset[str] | None = None,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.key_fn = key_fn
        self.transport = transport
        self.tasks = tasks if tasks is not None else frozenset({"llm"})

    def available(self) -> bool:
        return bool(self._key().strip())

    def invoke(self, call: Invocation) -> AdapterResult:
        key = self._key().strip()
        if not key:
            raise AdapterError(f"{self.provider} api key is empty")
        timeout = httpx.Timeout(call.timeout_s)
        try:
            with httpx.Client(timeout=timeout, transport=self.transport) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=_body(call),
                )
        except httpx.TimeoutException as exc:
            raise AdapterTimeout(f"{self.provider} timeout") from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"{self.provider} request failed") from exc
        if response.status_code >= 400:
            detail = response.text[:300]
            raise AdapterError(f"{self.provider} HTTP {response.status_code}: {detail}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise AdapterError(f"{self.provider} returned non-JSON") from exc
        content = _message_text(payload, self.provider)
        output = _parse_content(content, call.json_schema is not None, self.provider)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return AdapterResult(
            provider=self.provider,
            model=call.model,
            output=output,
            cost_cny=Decimal("0"),
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
            },
        )

    def _key(self) -> str:
        if self.key_fn is not None:
            return self.key_fn() or ""
        return self.api_key or ""


def _body(call: Invocation) -> dict[str, Any]:
    system = call.system or ""
    if call.json_schema is not None:
        schema_text = json.dumps(call.json_schema, ensure_ascii=False, sort_keys=True)
        system = (
            f"{system}\n\nReturn a JSON object that validates against this JSON Schema. "
            f"No markdown.\n{schema_text}"
        ).strip()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": call.prompt})
    body: dict[str, Any] = {"model": call.model, "messages": messages}
    if call.temperature is not None:
        body["temperature"] = call.temperature
    if call.seed is not None:
        body["seed"] = call.seed
    if call.json_schema is not None:
        body["response_format"] = {"type": "json_object"}
    max_tokens = call.params.get("max_tokens")
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return body


def _message_text(payload: dict[str, Any], provider: str) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AdapterError(f"{provider} response missing choices") from exc
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and "text" in part:
                parts.append(str(part["text"]))
        content = "".join(parts)
    if not isinstance(content, str) or not content.strip():
        raise AdapterError(f"{provider} response content is empty")
    return content


def _parse_content(content: str, structured: bool, provider: str) -> dict[str, Any]:
    if not structured:
        return {"text": content}
    text = content.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AdapterError(f"{provider} returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise AdapterError(f"{provider} JSON must be an object")
    return data
