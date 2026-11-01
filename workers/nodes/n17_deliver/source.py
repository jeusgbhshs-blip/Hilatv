"""Source-bound export identities and a pinned private clean-picture input."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from workers.media.timing import duration_budget
from workers.nodes.n15_compose.schema import Timeline
from workers.nodes.n17_deliver.qa import QAError
from workers.nodes.n17_deliver.schema import N17Input


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_key(
    payload: N17Input,
    media_hash: str,
    timeline: Timeline | None,
    render_config: dict[str, Any],
) -> str:
    """Canonical consumed inputs, excluding temporary paths and produce ids."""

    clock = {
        "target_duration_s": payload.target_duration_s,
        "intro_s": payload.intro_s,
        "outro_s": payload.outro_s,
    }
    if payload.target_duration_s is not None:
        budget = duration_budget(
            payload.target_duration_s, intro_s=payload.intro_s, outro_s=payload.outro_s
        )
        clock = {
            "target_duration_s": budget.total_s,
            "intro_s": budget.intro_s,
            "outro_s": budget.outro_s,
        }
    body = {
        "render_policy": 1,
        "source_media_hash": media_hash,
        "script": payload.script.model_dump(mode="json"),
        "brief": payload.brief.model_dump(mode="json"),
        "brand": payload.brand_kit.model_dump(mode="json") if payload.brand_kit else None,
        "variants": sorted(
            {item.language: item.model_dump(mode="json") for item in payload.variants}.values(),
            key=lambda item: item["language"],
        ),
        "tracks": sorted(
            [item.model_dump(mode="json") for item in payload.subject_tracks],
            key=lambda item: item["shot_id"],
        ),
        "clock": clock,
        "timeline": _timeline(timeline),
        "render": render_config,
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def pin_source(source: Path, work: Path, media_hash: str) -> Path:
    """Copy and rehash before FFmpeg; a mutable source cannot change the input."""

    dest = work / "clean-source.mp4"
    if dest.is_symlink():
        raise QAError("private export source must not be a symlink")
    if dest.is_file():
        if file_hash(dest) != media_hash:
            raise QAError("private export source no longer matches its source hash")
        return dest
    fd, raw = tempfile.mkstemp(prefix=".clean-source-", dir=work)
    temporary = Path(raw)
    try:
        digest = hashlib.sha256()
        with os.fdopen(fd, "wb") as output, source.open("rb") as incoming:
            for block in iter(lambda: incoming.read(1024 * 1024), b""):
                output.write(block)
                digest.update(block)
        if digest.hexdigest() != media_hash:
            raise QAError("clean picture changed while preparing its export; retry the source")
        temporary.chmod(0o400)
        os.replace(temporary, dest)
        return dest
    finally:
        temporary.unlink(missing_ok=True)


def _timeline(timeline: Timeline | None) -> dict[str, Any] | None:
    if timeline is None:
        return None
    fields = ("width", "height", "fps", "duration_s", "target_duration_s", "logo_status")
    clips = ("clip_id", "duration_s", "start_s", "transition_out", "placeholder")
    return {
        **{name: getattr(timeline, name) for name in fields},
        "clips": [{name: getattr(clip, name) for name in clips} for clip in timeline.clips],
    }
