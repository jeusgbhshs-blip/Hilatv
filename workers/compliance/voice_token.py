"""Short-lived proof that consent_gate already allowed this voice.

Only ``consent_gate`` may call ``issue_voice_token``. ``Gateway.tts`` verifies
the token and does not know how to mint one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from workers.identity.session import session_secret

_TTL_S = 120


class VoiceConsentError(Exception):
    pass


def issue_voice_token(voice: str, enterprise_id: str) -> str:
    now = int(time.time())
    payload = {
        "v": 1,
        "voice": voice,
        "eid": enterprise_id,
        "iat": now,
        "exp": now + _TTL_S,
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    digest = hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest()
    return body + "." + _b64(digest)


def verify_voice_token(token: str | None, voice: str | None) -> None:
    if not token:
        raise VoiceConsentError("tts 必须经过授权门")
    body, separator, digest = token.partition(".")
    if not body or not separator or not digest:
        raise VoiceConsentError("声音令牌无效")
    expected = hmac.new(_key(), body.encode("ascii"), hashlib.sha256).digest()
    try:
        actual = _unb64(digest)
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeError) as exc:
        raise VoiceConsentError("声音令牌无效") from exc
    if len(actual) != len(expected) or not hmac.compare_digest(expected, actual):
        raise VoiceConsentError("声音令牌无效")
    if not isinstance(payload, dict):
        raise VoiceConsentError("声音令牌无效")
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise VoiceConsentError("声音令牌已过期")
    expected_voice = voice or ""
    if payload.get("voice") != expected_voice:
        raise VoiceConsentError("声音令牌与请求不一致")


def _key() -> bytes:
    raw = os.getenv("HILATV_VOICE_CONSENT_SECRET", "").strip()
    material = raw.encode("utf-8") if raw else session_secret()
    return hmac.new(material, b"hilatv-voice-consent", hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)
