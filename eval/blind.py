"""Anonymous A/B packs for a later human blind review.

The reviewer file has pair ids and media paths only. The key maps a pair back
to the benchmark case. Control films are out of scope, so that side stays empty.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from eval.runner import CaseOutcome

_NS = uuid.UUID("b7e1c0a2-5d44-4e1a-9c3a-0a18e18e1818")


def pair_id_for(case_id: str) -> str:
    return str(uuid.uuid5(_NS, case_id))


def hilatv_side(case_id: str) -> str:
    return "a" if int(pair_id_for(case_id)[0], 16) % 2 == 0 else "b"


def write_blind(out: Path, outcomes: list[CaseOutcome]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    media_dir = out / "media"
    media_dir.mkdir(exist_ok=True)
    reviewer: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        pair_id = pair_id_for(outcome.case_id)
        side = hilatv_side(outcome.case_id)
        other = "b" if side == "a" else "a"
        media = _copy_media(outcome.deliverable, media_dir, f"{pair_id}-{side}.mp4")
        card = {
            "pair_id": pair_id,
            "a": {"media": media if side == "a" else None},
            "b": {"media": media if side == "b" else None},
        }
        reviewer.append(card)
        key_rows.append(
            {
                "pair_id": pair_id,
                "case_id": outcome.case_id,
                "industry": outcome.industry,
                "hilatv_side": side,
                "control_side": other,
                "control_status": "withheld",
                "deliverable": outcome.deliverable,
            }
        )
    _dump(out / "pairs.json", {"pairs": reviewer})
    _dump(out / "key.json", {"pairs": key_rows})


def _copy_media(deliverable: str | None, media_dir: Path, name: str) -> str | None:
    if not deliverable:
        return None
    source = Path(deliverable)
    if not source.is_file():
        return None
    target = media_dir / name
    shutil.copyfile(source, target)
    return f"media/{name}"


def _dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
