"""Structured JSON logs for the gateway process."""

from __future__ import annotations

import json
import sys
from decimal import Decimal


def log_event(event: str, **fields: object) -> None:
    record: dict[str, object] = {"event": event}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, Decimal):
            record[key] = format(value, "f")
        else:
            record[key] = value
    sys.stdout.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()
