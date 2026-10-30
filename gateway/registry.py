"""Build the default adapter map from environment variables."""

from __future__ import annotations

import os
from collections.abc import Callable

import httpx

from gateway.adapters.base import Adapter
from gateway.adapters.local_vision import LocalMattingAdapter, LocalRelightAdapter
from gateway.adapters.mock_adapter import MockAdapter
from gateway.adapters.openai_compat import OpenAICompatAdapter
from gateway.adapters.seedance import SeedanceAdapter
from gateway.adapters.seedream import SeedreamAdapter
from gateway.adapters.volc_asr import VolcAsrAdapter
from gateway.adapters.volc_tts import VolcTtsAdapter
from gateway.constants import (
    ARK_BASE_URL,
    DASHSCOPE_BASE_URL,
    DEEPSEEK_BASE_URL,
    DEFAULT_TTS_VOICE,
    GEMINI_BASE_URL,
    VOLC_ASR_BASE_URL,
    VOLC_ASR_RESOURCE,
    VOLC_TTS_BASE_URL,
)
from gateway.storage import ObjectStore, object_store_from_env


def build_registry(
    transport: httpx.BaseTransport | None = None,
    store: ObjectStore | None = None,
    *,
    poll_interval_s: float | None = None,
    poll_now: Callable[[], float] | None = None,
    poll_sleep: Callable[[float], None] | None = None,
) -> dict[str, Adapter]:
    media_store = object_store_from_env() if store is None else store
    interval = poll_interval_s
    if interval is None:
        raw = os.getenv("HILATV_POLL_INTERVAL_S", "2").strip() or "2"
        interval = float(raw)
    return {
        "mock": MockAdapter(store=media_store),
        "local_matting": LocalMattingAdapter(),
        "local_relight": LocalRelightAdapter(),
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
        "qwen_vl": OpenAICompatAdapter(
            provider="qwen_vl",
            base_url=os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_BASE_URL),
            key_fn=lambda: os.getenv("DASHSCOPE_API_KEY", ""),
            tasks=frozenset({"judge"}),
            transport=transport,
        ),
        "gemini": OpenAICompatAdapter(
            provider="gemini",
            base_url=os.getenv("GEMINI_BASE_URL", GEMINI_BASE_URL),
            key_fn=lambda: os.getenv("GEMINI_API_KEY", ""),
            tasks=frozenset({"judge"}),
            transport=transport,
        ),
        "seedream": SeedreamAdapter(
            base_url=os.getenv("SEEDREAM_BASE_URL", ARK_BASE_URL),
            key_fn=lambda: os.getenv("SEEDREAM_API_KEY", "") or os.getenv("ARK_API_KEY", ""),
            store=media_store,
            transport=transport,
        ),
        "seedance": SeedanceAdapter(
            base_url=os.getenv("SEEDANCE_BASE_URL", ARK_BASE_URL),
            key_fn=lambda: os.getenv("SEEDANCE_API_KEY", "") or os.getenv("ARK_API_KEY", ""),
            store=media_store,
            transport=transport,
            interval_s=interval,
            now=poll_now,
            sleep=poll_sleep,
        ),
        "volc_tts": VolcTtsAdapter(
            base_url=os.getenv("VOLC_TTS_BASE_URL", VOLC_TTS_BASE_URL),
            key_fn=lambda: os.getenv("VOLC_TTS_API_KEY", ""),
            app_id_fn=lambda: os.getenv("VOLC_TTS_APP_ID", ""),
            cluster=os.getenv("VOLC_TTS_CLUSTER", "volcano_tts").strip() or "volcano_tts",
            default_voice=os.getenv("VOLC_TTS_VOICE", DEFAULT_TTS_VOICE).strip()
            or DEFAULT_TTS_VOICE,
            store=media_store,
            transport=transport,
        ),
        "volc_asr": VolcAsrAdapter(
            base_url=os.getenv("VOLC_ASR_BASE_URL", VOLC_ASR_BASE_URL),
            key_fn=lambda: os.getenv("VOLC_ASR_API_KEY", ""),
            app_id_fn=lambda: os.getenv("VOLC_ASR_APP_ID", ""),
            resource_id=os.getenv("VOLC_ASR_RESOURCE_ID", VOLC_ASR_RESOURCE).strip()
            or VOLC_ASR_RESOURCE,
            store=media_store,
            transport=transport,
        ),
    }
