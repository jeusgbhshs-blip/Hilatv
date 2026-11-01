"""Structured JSON logs for the API process."""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from typing import Any
from urllib.parse import unquote

_SESSION_KEY = (
    r"(?:s|%[57]3)(?:e|%[46]5)(?:s|%[57]3)(?:s|%[57]3)(?:i|%[46]9)(?:o|%[46]f)(?:n|%[46]e)"
)
_SESSION_QUERY = re.compile(
    rf"((?:[?&]|%3f|%26|(?<![\w%])){_SESSION_KEY}(?:=|%3d))"
    r"((?:(?!%26|%23)[^\s&#\"'<>\\\)},;])+)",
    re.IGNORECASE,
)
_MARKER = "_hilatv_session_redaction"
_INSTALL_LOCK = threading.RLock()


def _redact_text(value: str) -> str:
    return _SESSION_QUERY.sub(lambda match: match.group(1) + "[REDACTED]", value)


def _redact(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, bytes):
        return _redact_text(value.decode("utf-8", errors="replace")).encode("utf-8")
    if depth > 20:
        return "[nested log data omitted]"
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]" if unquote(str(key)).lower() == "session" else _redact(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_redact(item, depth + 1) for item in value)
    if isinstance(value, list):
        return [_redact(item, depth + 1) for item in value]
    return value


class SessionQueryFilter(logging.Filter):
    """Sanitize records before a formatter can expose WebSocket credentials."""

    _hilatv_session_redaction = True

    def filter(self, record: logging.LogRecord) -> bool:
        record.args = _redact(record.args)
        if not isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        try:
            # Handle credentials assembled across the template/argument boundary
            # without breaking Uvicorn AccessFormatter's normal five arguments.
            rendered = record.getMessage()
            clean = _redact_text(rendered)
            if clean != rendered:
                record.msg, record.args = clean, ()
            else:
                record.msg = _redact(record.msg)
        except (TypeError, ValueError, KeyError):
            # A sanitized template may have replaced a credential placeholder.
            # Fall back to its safe text instead of logging an error + raw args.
            record.msg, record.args = _redact_text(str(record.msg)), ()
        if record.exc_info:
            record.exc_text = _redact_text(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = _redact_text(record.exc_text)
        if record.stack_info:
            record.stack_info = _redact_text(record.stack_info)
        return True


def install_session_log_redaction() -> None:
    """Filter confirmed Uvicorn emitters without changing logging configuration."""
    with _INSTALL_LOCK:
        redactor = SessionQueryFilter()
        for name in ("uvicorn.error", "uvicorn.access"):
            logger = logging.getLogger(name)
            if not any(getattr(item, _MARKER, False) for item in logger.filters):
                logger.addFilter(redactor)


def log_event(event: str, **fields: object) -> None:
    record: dict[str, object] = {"event": event}
    for key, value in fields.items():
        if value is not None:
            record[key] = value
    sys.stdout.write(json.dumps(_redact(record), ensure_ascii=False) + "\n")
    sys.stdout.flush()
