"""Shared gateway constants. Vendor URLs are HTTP endpoints, not SDKs."""

from __future__ import annotations

TASKS = frozenset({"llm", "image", "video", "tts", "asr", "music", "judge"})

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
VOLC_TTS_BASE_URL = "https://openspeech.bytedance.com"

# SPEC Brand Kit voice id mapped onto a documented Doubao voice. Override with VOLC_TTS_VOICE.
DEFAULT_TTS_VOICE = "zh_male_M392_conversation_wvae_bigtts"
TTS_VOICE_ALIASES = {"zh_male_steady": DEFAULT_TTS_VOICE}

# Image and video models must not paint copy. The render nodes overlay text.
NO_RENDERED_TEXT = (
    "no text, no letters, no captions, no subtitles, no logo, no watermark, "
    "no price, no phone number, no written characters. "
    "画面中不要出现任何文字、字母、数字水印、Logo、价格或电话。"
)

DEFAULT_JSON_SYSTEM = (
    "You are a precise assistant. Return a JSON object and nothing else. "
    "The object must validate against the provided JSON Schema."
)

ALERT_MARKER = "<!-- hilatv:alerts -->"
ALERT_HEADING = "## 告警（预算超限等，由网关自动追加）"
DAILY_LOG_HEADING = "## 每日日志"
