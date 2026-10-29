"""OpenAI-compatible HTTP adapter. Transport is in-process; no vendor SDK."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from pydantic import BaseModel

from gateway.adapters.openai_compat import OpenAICompatAdapter
from gateway.errors import AdapterError, AdapterTimeout
from gateway.models import Invocation
from gateway.tests.conftest import build_gateway

ROUTES = """
version: 1
defaults:
  timeout_s: 5
routes:
  - id: llm
    task: llm
    shot_type: "*"
    language: "*"
    primary: {provider: deepseek, model: deepseek-chat}
    fallbacks: []
"""


class Goal(BaseModel):
    goal: str


def _call() -> Invocation:
    return Invocation(
        task="llm",
        prompt="hello",
        model="deepseek-chat",
        provider="deepseek",
        system="Return JSON.",
        seed=9,
        temperature=0.2,
        timeout_s=5,
        json_schema=Goal.model_json_schema(),
        schema_name="Goal",
    )


def test_http_success_sends_schema_and_bearer_token() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"goal": "获客"})}}],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
            },
        )

    adapter = OpenAICompatAdapter(
        provider="deepseek",
        api_key="sk-test-not-real",
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(handler),
    )
    result = adapter.invoke(_call())
    assert seen["auth"] == "Bearer sk-test-not-real"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {"type": "json_object"}
    assert body["seed"] == 9
    assert "JSON Schema" in body["messages"][0]["content"]
    assert result.output == {"goal": "获客"}
    assert result.usage["prompt_tokens"] == 1_000_000
    assert "sk-test-not-real" not in json.dumps(result.output)


def test_http_error_and_timeout_do_not_leak_the_key() -> None:
    key = "sk-test-not-real"

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="upstream blew up")

    adapter = OpenAICompatAdapter(
        provider="deepseek",
        api_key=key,
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(broken),
    )
    with pytest.raises(AdapterError) as err:
        adapter.invoke(_call())
    assert key not in str(err.value)
    assert "500" in str(err.value)

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow")

    timed = OpenAICompatAdapter(
        provider="deepseek",
        api_key=key,
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(slow),
    )
    with pytest.raises(AdapterTimeout) as timeout:
        timed.invoke(_call())
    assert key not in str(timeout.value)


def test_gateway_prices_live_usage(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"goal": "获客"})}}],
                "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
            },
        )

    adapter = OpenAICompatAdapter(
        provider="deepseek",
        api_key="sk-test-not-real",
        base_url="https://api.deepseek.com",
        transport=httpx.MockTransport(handler),
    )
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"deepseek": adapter},
        limits=(True, Decimal("100"), Decimal("100")),
    )
    out = gateway.generate_text("need a goal", schema=Goal, seed=1)
    assert out == {"goal": "获客"}
    row = gateway.store.list_logs()[-1]
    assert row["live"] == 1
    assert row["provider"] == "deepseek"
    assert Decimal(row["cost_cny"]) == Decimal("10.000000")
    assert "sk-test-not-real" not in json.dumps(row["params"])


def test_empty_key_is_unavailable() -> None:
    adapter = OpenAICompatAdapter(
        provider="deepseek",
        api_key="",
        base_url="https://api.deepseek.com",
    )
    assert adapter.available() is False
