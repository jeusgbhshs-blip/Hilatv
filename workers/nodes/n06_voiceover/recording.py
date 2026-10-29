"""User-recording alignment. Present as an interface; T07 does not accept it."""

from __future__ import annotations

from typing import Any

NODE = "n06_voiceover"


def align_user_recording(
    audio_uri: str,
    gateway: Any,
    *,
    language: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Ask the gateway ASR to time a take the user recorded. Not used by ``run``."""

    if not audio_uri.strip():
        raise ValueError("audio_uri is empty")
    result = gateway.asr(
        audio_uri,
        language=language,
        project_id=project_id,
        node=NODE,
        params={"user_recording": True},
    )
    if not isinstance(result, dict):
        raise ValueError("asr returned a non-object")
    return result
