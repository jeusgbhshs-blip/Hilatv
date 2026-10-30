"""Delivery gates around N17. Input review runs before encode. Output review after."""

from __future__ import annotations

from typing import Any

from workers.brand_kit.people import ConsentError
from workers.compliance.evidence import EvidenceError
from workers.compliance.licences import assemble
from workers.compliance.metadata import content_id, metadata_args
from workers.compliance.note import render_note, write_note
from workers.nodes.n16_review.node import run as review
from workers.nodes.n16_review.qa import QAError as ReviewError
from workers.nodes.n17_deliver.qa import QAError
from workers.nodes.n17_deliver.schema import DeliveryVersion, N17Input
from workers.schemas.label_lock import LabelLocked, walk_label_edits
from workers.schemas.licensing import today_shanghai


def open_delivery(
    request_project: str,
    payload: N17Input,
    raw_payload: dict[str, Any],
    *,
    gateway: Any,
    attempt: int,
) -> None:
    """Reject a label edit, unconsented people, and a failing input review."""

    try:
        walk_label_edits(raw_payload)
    except LabelLocked as exc:
        raise QAError(str(exc)) from exc
    _people(payload)
    summary = _licences(request_project, payload)
    _review(
        request_project,
        payload,
        gateway=gateway,
        attempt=attempt,
        stage="input",
        summary=summary,
        media_paths=[],
        texts=[],
    )


def close_delivery(
    request_project: str,
    payload: N17Input,
    versions: list[DeliveryVersion],
    *,
    gateway: Any,
    attempt: int,
    root: Any,
) -> dict[str, Any]:
    """Stamp implicit metadata, review the output, and write the rights note."""

    from workers.media.ffmpeg import run_ffmpeg

    for version in versions:
        ident = content_id(
            request_project,
            version.version_id,
            version.aspect_ratio,
            version.language,
        )
        args = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            version.path,
            "-c",
            "copy",
            "-map_metadata",
            "-1",
            *metadata_args(content_id=ident),
            "-fflags",
            "+bitexact",
            "-flags",
            "+bitexact",
            version.path + ".aigc.mp4",
        ]
        run_ffmpeg(args)
        stamped = version.path + ".aigc.mp4"
        from pathlib import Path

        Path(stamped).replace(version.path)
    summary = _licences(request_project, payload, root=root)
    texts = [box.text for version in versions for box in version.overlays]
    reviewed = _review(
        request_project,
        payload,
        gateway=gateway,
        attempt=attempt,
        stage="output",
        summary=summary,
        media_paths=[version.path for version in versions],
        texts=texts,
    )
    note = render_note(
        summary,
        manual_review=bool(reviewed.get("manual_review")),
        sectors=list(reviewed.get("manual_review_sectors") or []),
        variants=len(versions),
    )
    path = write_note(root, note)
    return {
        "materials_note": str(path),
        "manual_review": bool(reviewed.get("manual_review")),
        "manual_review_sectors": list(reviewed.get("manual_review_sectors") or []),
        "licensing": summary.model_dump(mode="json"),
        "implicit_label": "AIGC",
        "explicit_label": "AI生成",
    }


def _people(payload: N17Input) -> None:
    if payload.script is None:
        return
    try:
        for shot in payload.script.shots:
            from workers.compliance.consent_gate import (
                assert_generation_allowed,
                assert_voice_allowed,
            )

            assert_generation_allowed(shot, payload.brand_kit, archived=payload.brand_archived)
        voice = payload.brand_kit.voice.tts_voice if payload.brand_kit is not None else None
        assert_voice_allowed(voice, payload.brand_kit, archived=payload.brand_archived)
    except ConsentError as exc:
        raise QAError(str(exc)) from exc


def _licences(project_id: str, payload: N17Input, root: Any | None = None):
    from pathlib import Path

    from workers.workflow.store import project_path

    base = Path(root) if root is not None else project_path(project_id, create=True)
    try:
        return assemble(
            project_id,
            payload.licensing,
            root=base,
            today=today_shanghai(),
        )
    except EvidenceError as exc:
        raise QAError(str(exc)) from exc


def _review(
    project_id: str,
    payload: N17Input,
    *,
    gateway: Any,
    attempt: int,
    stage: str,
    summary: Any,
    media_paths: list[str],
    texts: list[str],
) -> dict[str, Any]:
    try:
        result = review(
            {
                "project_id": project_id,
                "attempt": attempt,
                "payload": {
                    "stage": stage,
                    "brief": payload.brief.model_dump(mode="json"),
                    "script": payload.script.model_dump(mode="json"),
                    "brand_kit": (
                        payload.brand_kit.model_dump(mode="json") if payload.brand_kit else None
                    ),
                    "brand_archived": payload.brand_archived,
                    "texts": texts,
                    "media_paths": media_paths,
                    "licensing": summary.model_dump(mode="json"),
                    "instruction": payload.instruction,
                },
            },
            gateway=gateway,
        )
    except ReviewError as exc:
        raise QAError(str(exc)) from exc
    if result.payload.get("passed") is not True:
        reasons = result.payload.get("block_reasons") or ["compliance review failed"]
        raise QAError("; ".join(str(item) for item in reasons))
    return result.payload
