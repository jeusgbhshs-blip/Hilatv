"""Server-issued session tokens. The enterprise id is inside the token, not the request."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_PROCESS_SECRET = secrets.token_bytes(32)
_SESSION_TTL_S = 30 * 24 * 60 * 60
_REVOKED: set[str] = set()
_REVOKE_LOCK = threading.RLock()


class SessionError(Exception):
    """The token is missing, forged, expired, or revoked. The message is not for clients."""


class SessionConfigError(RuntimeError):
    """Live mode is on and HILATV_SESSION_SECRET is not set."""


@dataclass(frozen=True)
class Identity:
    enterprise_id: str
    member_id: str
    token: str


def live_mode() -> bool:
    return os.getenv("HILATV_LIVE", "0").strip() == "1"


def assert_live_session_configured() -> None:
    """Refuse to run a live process on a per-process random session secret."""

    if live_mode():
        session_secret()


def session_secret() -> bytes:
    raw = os.getenv("HILATV_SESSION_SECRET", "").strip()
    if raw:
        return raw.encode("utf-8")
    if live_mode():
        raise SessionConfigError("HILATV_SESSION_SECRET is required when HILATV_LIVE=1")
    return _PROCESS_SECRET


def admin_secret_matches(provided: str) -> bool:
    """True only when live registration presents the configured admin secret."""

    expected = os.getenv("HILATV_SESSION_ADMIN_SECRET", "").strip()
    if not expected or not provided:
        return False
    left = hashlib.sha256(provided.encode("utf-8")).digest()
    right = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(left, right)


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
    jti = payload.get("jti")
    if not isinstance(enterprise_id, str) or not isinstance(member_id, str):
        raise SessionError("missing subject")
    if not isinstance(jti, str) or not jti:
        raise SessionError("missing jti")
    if _is_revoked(jti):
        raise SessionError("revoked")
    try:
        enterprise_id = _canonical(enterprise_id)
        member_id = str(uuid.UUID(member_id))
    except (ValueError, SessionError) as exc:
        raise SessionError("bad subject") from exc
    return Identity(enterprise_id=enterprise_id, member_id=member_id, token=token)


def revoke_session(token: str) -> str:
    """Reject this token on every later verify. A leak is not replayable for 30 days."""

    payload = _unsign(token, purpose=b"session")
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        raise SessionError("missing jti")
    with _REVOKE_LOCK:
        _REVOKED.add(jti)
        found = _load_revoked()
        found.add(jti)
        _store_revoked(found)
    return jti


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
        "jti": str(uuid.uuid4()),
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


def _revocation_path() -> Path:
    raw = os.getenv("HILATV_SESSION_REVOCATION_PATH", "").strip()
    if raw:
        return Path(raw)
    root = os.getenv("HILATV_PROJECT_DIR", "").strip()
    if not root:
        if live_mode():
            raise SessionConfigError("HILATV_PROJECT_DIR is required when HILATV_LIVE=1")
        return Path(tempfile.gettempdir()) / "hilatv-sessions" / "revoked-sessions.json"
    return Path(root) / "revoked-sessions.json"


def _load_revoked() -> set[str]:
    """Read the revocation list. A missing file is empty. A bad file rejects the request."""

    path = _revocation_path()
    with _revocation_lock(path):
        return _read_revoked(path)


def _store_revoked(found: set[str]) -> None:
    path = _revocation_path()
    with _revocation_lock(path):
        current = _read_revoked(path)
        _write_revoked(path, current | found)


def _is_revoked(jti: str) -> bool:
    with _REVOKE_LOCK:
        if jti in _REVOKED:
            return True
        found = _load_revoked()
        if jti in found:
            _REVOKED.add(jti)
            return True
    return False


@contextmanager
def _revocation_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    handle = lock_path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _read_revoked(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SessionError("revocation list is unreadable") from exc
    if not raw.strip():
        raise SessionError("revocation list is unreadable")
    try:
        loaded = json.loads(raw)
    except ValueError as exc:
        raise SessionError("revocation list is unreadable") from exc
    bad_item = not isinstance(loaded, list) or any(
        not isinstance(item, str) or not item for item in loaded
    )
    if bad_item:
        raise SessionError("revocation list is unreadable")
    return set(loaded)


def _write_revoked(path: Path, found: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(sorted(found))
    fd, tmp_name = tempfile.mkstemp(prefix=".revoked.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)
