"""Build the default adapter map from environment variables."""

from __future__ import annotations

import os

import httpx

from gateway.adapters.base import Adapter
from gateway.adapters.mock_adapter import MockAdapter
from gateway.adapters.openai_compat import OpenAICompatAdapter
from gateway.constants import ARK_BASE_URL, DASHSCOPE_BASE_URL, DEEPSEEK_BASE_URL


def build_registry(transport: httpx.BaseTransport | None = None) -> dict[str, Adapter]:
    return {
        "mock": MockAdapter(),
        "deepseek": OpenAICompatAdapter(
            provider="deepseek",
            base_url=os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
            key_fn=lambda: os.getenv("DEEPSEEK_API_KEY", ""),
            transport=transport,
        ),
        "dashscope": OpenAICompatAdapter(
            provider="dashscope",
            base_url=os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL),
            key_fn=lambda: os.getenv("DASHSCOPE_API_KEY", ""),
            transport=transport,
        ),
        "ark": OpenAICompatAdapter(
            provider="ark",
            base_url=os.getenv("ARK_BASE_URL", ARK_BASE_URL),
            key_fn=lambda: os.getenv("ARK_API_KEY", ""),
            transport=transport,
        ),
    }
