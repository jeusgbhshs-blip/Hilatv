"""Server-issued session tokens. The enterprise id is inside the token, not the request."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass

_PROCESS_SECRET = secrets.token_bytes(32)
_SESSION_TTL_S = 30 * 24 * 60 * 60


class SessionError(Exception):
    """The token is missing, forged, or expired. The message is not for clients."""


@dataclass(frozen=True)
class Identity:
    enterprise_id: str
    member_id: str
    token: str


def session_secret() -> bytes:
    raw = os.getenv("HILATV_SESSION_SECRET", "").strip()
    if raw:
        return raw.encode("utf-8")
    return _PROCESS_SECRET


def open_session() -> Identity:
    """Mint a new enterprise. Callers cannot choose the id."""

    return _issue(str(uuid.uuid4()), str(uuid.uuid4()))


def mint_session_for_tests(enterprise_id: str, member_id: str | None = None) -> Identity:
    """Fixture helper. Not an HTTP route and not for request bodies."""

    return _issue(_canonical(enterprise_id), member_id or str(uuid.uuid4()))


def verify_session(token: str) -> Identity:
    payload = _unsign(token, purpose=b"session")
    enterprise_id = payload.get("eid")
    member_id = payload.get("sub")
    if not isinstance(enterprise_id, str) or not isinstance(member_id, str):
        raise SessionError("missing subject")
    try:
        enterprise_id = _canonical(enterprise_id)
        member_id = str(uuid.UUID(member_id))
    except (ValueError, SessionError) as exc:
        raise SessionError("bad subject") from exc
    return Identity(enterprise_id=enterprise_id, member_id=member_id, token=token)


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = value.strip()
    return token or None


def canonical_enterprise(value: str) -> str | None:
    try:
        return _canonical(value)
    except SessionError:
        return None


def _issue(enterprise_id: str, member_id: str) -> Identity:
    now = int(time.time())
    payload = {
        "v": 1,
        "eid": enterprise_id,
        "sub": str(uuid.UUID(member_id)),
        "iat": now,
        "exp": now + _SESSION_TTL_S,
    }
    token = _sign(payload, purpose=b"session")
    return Identity(enterprise_id=enterprise_id, member_id=payload["sub"], token=token)


def _canonical(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise SessionError("enterprise id is not a uuid") from exc


def _sign(payload: dict[str, object], *, purpose: bytes) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    digest = hmac.new(_key(purpose), body.encode("ascii"), hashlib.sha256).digest()
    return body + "." + _b64(digest)


def _unsign(token: str, *, purpose: bytes) -> dict[str, object]:
    body, separator, digest = token.partition(".")
    if not body or not separator or not digest:
        raise SessionError("malformed")
    expected = hmac.new(_key(purpose), body.encode("ascii"), hashlib.sha256).digest()
    try:
        actual = _unb64(digest)
    except (ValueError, UnicodeError) as exc:
        raise SessionError("malformed") from exc
    if len(actual) != len(expected) or not hmac.compare_digest(expected, actual):
        raise SessionError("bad signature")
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeError) as exc:
        raise SessionError("malformed") from exc
    if not isinstance(payload, dict):
        raise SessionError("malformed")
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise SessionError("expired")
    return payload


def _key(purpose: bytes) -> bytes:
    return hmac.new(session_secret(), purpose, hashlib.sha256).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)
