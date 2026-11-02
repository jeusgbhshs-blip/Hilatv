"""Only synthetic credentials; exercise the actual stdlib/Uvicorn log records."""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from uvicorn.logging import AccessFormatter

from app.logging import SessionQueryFilter, install_session_log_redaction, log_event

TOKEN = "SYNTHETIC_SESSION_FOR_LOG_TEST.signature"


@pytest.mark.parametrize(
    "path",
    [
        f"/v1/projects/demo/progress?session={TOKEN}",
        f"/v1/projects/demo/progress?debug=1&session={TOKEN}&mode=preview",
        f"/v1/projects/demo/progress?SESSION={TOKEN}&mode=preview",
        f"/v1/projects/demo/progress?%73ession={TOKEN}&mode=preview",
        f"/v1/projects/demo/progress?%73%65%73%73%69%6f%6e={TOKEN}&mode=preview",
        f"/v1/projects/demo/progress?session={TOKEN}&session={TOKEN}&mode=preview",
        f"/v1/projects/demo/progress%3Fsession%3D{TOKEN}%26mode%3Dpreview",
    ],
)
def test_real_record_argument_is_sanitized_before_formatting(path):
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        '127.0.0.1 - "WebSocket %s" [accepted]',
        (path,),
        None,
    )
    redactor = SessionQueryFilter()
    assert redactor.filter(record) is True
    assert TOKEN not in repr(record.args) and TOKEN not in str(record.msg)
    output = logging.Formatter("%(levelname)s:%(message)s").format(record)
    assert TOKEN not in output and "[REDACTED]" in output
    assert "/v1/projects/demo/progress" in output and "accepted" in output
    if "mode" in path:
        assert "mode" in output and "preview" in output
    before = (record.msg, record.args)
    redactor.filter(record)
    assert (record.msg, record.args) == before


@pytest.mark.parametrize(
    "message,args",
    [
        (f"WebSocket /progress?session={TOKEN}&debug=1", ()),
        ("WebSocket /progress?session=%s phase=%s", (TOKEN, "accepted")),
        ("WebSocket %s?session=%s phase=%s", ("/progress", TOKEN, "accepted")),
        (
            "request %(path)s status=%(status)d",
            ({"path": f"/progress?session={TOKEN}", "status": 101},),
        ),
    ],
)
def test_literal_templates_and_mapping_arguments_keep_useful_context(message, args):
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, message, args, None)
    SessionQueryFilter().filter(record)
    assert TOKEN not in str(record.msg) and TOKEN not in repr(record.args)
    output = record.getMessage()
    assert TOKEN not in output and "/progress" in output
    if "phase" in message:
        assert "phase=accepted" in output
    if "status" in message:
        assert "status=101" in output


def test_installed_access_filter_preserves_real_five_argument_formatter(monkeypatch):
    logger = logging.getLogger("uvicorn.access")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False)
    )
    monkeypatch.setattr(logger, "handlers", [handler])
    monkeypatch.setattr(logger, "filters", [])
    monkeypatch.setattr(logger, "propagate", False)
    install_session_log_redaction()
    args = ("127.0.0.1:12345", "GET", f"/preview?session={TOKEN}&debug=1", "1.1", 206)
    record = logger.makeRecord(
        logger.name, logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', args, None
    )
    logger.handle(record)
    assert isinstance(record.args, tuple) and len(record.args) == 5
    assert record.args[4] == 206
    output = stream.getvalue()
    assert TOKEN not in output and "GET /preview?session=[REDACTED]&debug=1 HTTP/1.1" in output
    assert "206 Partial Content" in output
    assert TOKEN in args[2]  # Only the log record copy changed, not the actual request.


def test_installed_error_filter_sanitizes_exception_and_stack(monkeypatch):
    logger = logging.getLogger("uvicorn.error")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    monkeypatch.setattr(logger, "handlers", [handler])
    monkeypatch.setattr(logger, "filters", [])
    monkeypatch.setattr(logger, "propagate", False)
    install_session_log_redaction()
    try:
        raise ValueError(f"synthetic WebSocket failure /progress?session={TOKEN}&debug=1")
    except ValueError:
        record = logger.makeRecord(
            logger.name,
            logging.ERROR,
            __file__,
            1,
            "ASGI exception",
            (),
            sys.exc_info(),
            sinfo=f"synthetic stack /progress?session={TOKEN}",
        )
    logger.handle(record)
    output = stream.getvalue()
    assert TOKEN not in output
    assert "ValueError" in output and "ASGI exception" in output and "debug=1" in output


def test_api_json_output_redacts_nested_query_and_session_fields_without_mutation(capsys):
    fields = {"url": f"/progress?session={TOKEN}&debug=1", "session": TOKEN}
    log_event("ws_debug", details=[fields], retry=2)
    output = capsys.readouterr().out
    assert TOKEN not in output
    body = json.loads(output)
    assert body["event"] == "ws_debug" and body["retry"] == 2
    assert body["details"][0]["session"] == "[REDACTED]"
    assert "debug=1" in body["details"][0]["url"]
    assert fields["session"] == TOKEN


def test_install_is_idempotent_without_touching_factory_levels_or_handlers(monkeypatch):
    names = ("uvicorn.error", "uvicorn.access")
    existing = logging.Filter()
    for name in names:
        monkeypatch.setattr(logging.getLogger(name), "filters", [existing])
    root = logging.getLogger()
    snapshot = (logging.getLogRecordFactory(), root.level, tuple(root.handlers))
    before = [
        (logging.getLogger(name).level, tuple(logging.getLogger(name).handlers)) for name in names
    ]
    install_session_log_redaction()
    install_session_log_redaction()
    assert snapshot == (logging.getLogRecordFactory(), root.level, tuple(root.handlers))
    assert before == [
        (logging.getLogger(name).level, tuple(logging.getLogger(name).handlers)) for name in names
    ]
    for name in names:
        filters = logging.getLogger(name).filters
        assert existing in filters
        assert sum(bool(getattr(item, "_hilatv_session_redaction", False)) for item in filters) == 1


def test_importing_main_installs_filters_before_any_websocket_request(tmp_path):
    root = Path(__file__).resolve().parents[3]
    script = """
import logging
before = logging.getLogRecordFactory()
import app.main
assert logging.getLogRecordFactory() is before
for name in ('uvicorn.error', 'uvicorn.access'):
    filters = logging.getLogger(name).filters
    assert any(getattr(f, '_hilatv_session_redaction', False) for f in filters)
"""
    # The subprocess imports the API package directly; same path the API server uses.
    existing = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "HILATV_LIVE": "0",
        "HILATV_PROJECT_DIR": str(tmp_path),
        "PYTHONPATH": os.pathsep.join(
            item for item in (str(root / "apps" / "api"), str(root), existing) if item
        ),
    }
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        timeout=30,
    )
