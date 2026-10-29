"""Model gateway. Business code calls this package, never a vendor SDK."""

from gateway.service import (
    Gateway,
    asr,
    generate_image,
    generate_text,
    generate_video,
    get_gateway,
    judge,
    music,
    reset_gateway,
    tts,
)

__all__ = [
    "Gateway",
    "asr",
    "generate_image",
    "generate_text",
    "generate_video",
    "get_gateway",
    "judge",
    "music",
    "reset_gateway",
    "tts",
]
