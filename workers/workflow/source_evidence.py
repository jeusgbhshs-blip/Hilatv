"""Resolve source/payment claims against the current server gateway journal.

No model invocation is made. Human-readable references, execution_mode and
settled booleans in a review document are never payment receipts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

_MEDIA_TASKS = {"image", "video", "tts", "asr", "music", "content_safety"}
_NODE_TASKS = {
    "n01_brief": "llm",
    "n03_concept": "llm",
    "n04_script": "llm",
    "n05_storyboard": "llm",
    "n06_voiceover": "tts",
    "n08_keyframe": "image",
    "n09_keyframe_qa": "judge",
    "n10_video": "video",
    "n12_music": "music",
}


def verified_sources(
    store: Any,
    project_id: str,
    source: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    nodes_directory: Path,
) -> bool:
    records = source.get("records")
    if not isinstance(records, list) or not records:
        return False
    verified = []
    try:
        for item in records:
            if not isinstance(item, dict):
                return False
            row = _receipt(store, project_id, item.get("gateway_log_id"))
            if row is None:
                return False
            if item.get("billing_status") == "not_billable" and _cost(row.get("cost_cny")) != 0:
                return False
            if row.get("status") == "cache_hit":
                origin = _receipt(store, project_id, item.get("origin_log_id"))
                if (
                    origin is None
                    or origin.get("status") != "ok"
                    or any(origin.get(key) != row.get(key) for key in ("task", "provider", "model"))
                    or _request_params(origin) != _request_params(row)
                    or origin["output"] != row["output"]
                    or _cost(row.get("cost_cny")) != 0
                ):
                    return False
            if item.get("output_uri") is not None and item["output_uri"] != row["output"].get(
                "uri"
            ):
                return False
            verified.append(row)
    except Exception:
        # A missing/unavailable journal or an old schema is not evidence of a
        # free successful live call. Error details must not leak connection data.
        return False
    for node, task in _NODE_TASKS.items():
        if (nodes_directory / f"{node}.json").is_file():
            if node == "n06_voiceover" and not _rows(state.get("voiceovers")):
                continue
            names = {node, "n09_keyframe"} if node == "n09_keyframe_qa" else {node}
            if not any(row.get("node") in names and row.get("task") == task for row in verified):
                return False
    for task, nodes in (
        ("judge", {"n16_final_review"}),
        ("asr", {"n16_final_review"}),
        ("content_safety", {"n16_final_review", "n16_review"}),
    ):
        if not any(
            row.get("task") == task
            and row.get("node") in nodes
            and row["params"].get("media_hash") == source.get("media_hash")
            for row in verified
        ):
            return False
    from workers.nodes.n06_voiceover.audio import character_error_rate

    script = state.get("script")
    expected = (
        "".join(
            str(row.get("voiceover") or "")
            for row in _rows(script.get("shots"))
            if isinstance(row, dict)
        )
        if isinstance(script, dict)
        else ""
    )
    spoken_ids = (
        {
            row.get("shot_id")
            for row in _rows(script.get("shots"))
            if isinstance(row, dict) and str(row.get("voiceover") or "").strip()
        }
        if isinstance(script, dict)
        else set()
    )
    take_ids = {
        row.get("shot_id") for row in _rows(state.get("voiceovers")) if isinstance(row, dict)
    }
    if not spoken_ids.issubset(take_ids):
        return False
    if not any(
        row.get("task") == "asr"
        and row.get("node") == "n16_final_review"
        and row["params"].get("media_hash") == source.get("media_hash")
        and isinstance(row["output"].get("text"), str)
        and character_error_rate(expected, row["output"]["text"]) < 0.02
        for row in verified
    ):
        return False
    used = []
    for name, task in (("keyframes", "image"), ("videos", "video")):
        for candidate in _rows(state.get(name)):
            if not isinstance(candidate, dict) or candidate.get("selected") is not True:
                continue
            params = candidate.get("params")
            params = params if isinstance(params, dict) else {}
            used.append(
                (
                    task,
                    candidate.get("shot_id"),
                    params.get("generation_source_uri") or candidate.get("uri"),
                )
            )
    for take in _rows(state.get("voiceovers")):
        if isinstance(take, dict):
            used.append(("tts", take.get("shot_id"), take.get("uri")))
    track = state.get("audio_track")
    if isinstance(track, dict):
        used.append(("music", None, track.get("music_source_uri")))
    return bool(used) and all(
        isinstance(uri, str)
        and uri
        and any(
            row.get("task") == task
            and (shot is None or row.get("shot_id") == shot)
            and row["output"].get("uri") == uri
            for row in verified
        )
        for task, shot, uri in used
    )


def _receipt(store: Any, project_id: str, log_id: Any) -> dict[str, Any] | None:
    if not isinstance(log_id, str):
        return None
    try:
        UUID(log_id)
    except ValueError:
        return None
    rows = store.fetchall(
        "SELECT * FROM call_logs WHERE id = %s AND project_id = %s", (log_id, project_id)
    )
    if len(rows) != 1:
        return None
    row = rows[0]
    output = row.get("output")
    output = json.loads(output) if isinstance(output, str) else output
    cost = _cost(row.get("cost_cny"))
    if (
        row.get("status") == "ok"
        and row.get("live") != 1
        or str(row.get("provider", "")).startswith("mock")
        or str(row.get("model", "")).startswith("mock")
        or row.get("status") not in {"ok", "cache_hit"}
        or not str(row.get("provider", "")).strip()
        or not str(row.get("model", "")).strip()
        or not isinstance(output, dict)
        or output.get("mock") is True
        or row.get("task") in _MEDIA_TASKS
        and output.get("mock") is not False
        or cost is None
        or row.get("fallback_reason") == "billing_unknown"
    ):
        return None
    if row.get("status") == "cache_hit" and (
        row.get("live") != 0 or row.get("cache_hit") != 1 or cost != 0
    ):
        return None
    if row.get("status") == "ok":
        reservations = store.fetchall(
            "SELECT state, amount_cny, context FROM budget_reservations WHERE id = %s", (log_id,)
        )
        if len(reservations) != 1 or reservations[0].get("state") != "settled":
            return None
        bound = _cost(reservations[0].get("amount_cny"))
        context = reservations[0].get("context")
        context = json.loads(context) if isinstance(context, str) else context
        if (
            bound is None
            or cost > bound
            or not isinstance(context, dict)
            or context.get("project_id") != project_id
        ):
            return None
    params = row.get("params")
    params = json.loads(params) if isinstance(params, str) else params
    return {**row, "output": output, "params": params if isinstance(params, dict) else {}}


def _cost(value: Any) -> Decimal | None:
    try:
        amount = Decimal(str(value))
    except (ValueError, InvalidOperation):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def _request_params(row: Mapping[str, Any]) -> dict[str, Any]:
    # Only these two fields are added by budget admission after the cache key
    # is computed. Keep actual prompts/schema/seed and media/image hashes bound.
    return {
        key: value
        for key, value in row["params"].items()
        if key not in {"budget_reservation_id", "budget_reserved_cny"}
    }


def _rows(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
