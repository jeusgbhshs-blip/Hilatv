"""Structured JSON logs for the API process."""

from __future__ import annotations

import json
import sys


def log_event(event: str, **fields: object) -> None:
    record: dict[str, object] = {"event": event}
    for key, value in fields.items():
        if value is not None:
            record[key] = value
    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()
