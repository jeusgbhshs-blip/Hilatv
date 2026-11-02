"""Server-owned delivery evidence; generation completion is not a release.

Readiness never calls a model. HTTP callers may ask to preview a decodable
project file, but cannot supply a release flag or final-review document.
HP16 will call record_delivery_evidence after the real final-review node.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Mapping
from datetime import date
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from workers.brand_kit.people import ConsentError
from workers.compliance.consent_gate import archive_people, assert_voice_allowed
from workers.compliance.licences import today_shanghai
from workers.compliance.metadata import PLACEHOLDER_PRODUCER, TEST_HMAC_KEY, hmac_key, read_aigc
from workers.media.audio import combine_provenance
from workers.media.packaging import FPS
from workers.nodes.n12_music.schema import LicenseRecord, incomplete_reason
from workers.nodes.n18_revision.concept_gate import classify_concept
from workers.qa.scores import PASS_TOTAL, is_quality_pass
from workers.schemas.asset import QAReport
from workers.workflow.contract import PIPELINE
from workers.workflow.store import contained_file, project_path, project_root, valid_project_id

_HASH = re.compile(r"^[a-f0-9]{64}$")
_KINDS = {"live", "mock", "mixed", "unknown"}
_CONTEXT = (
    "script",
    "brief",
    "brand_kit",
    "elements",
    "licensing_summary",
    "voiceovers",
    "audio_track",
    "aligned_script",
    "timeline",
    "logo_status",
)


def state_from_directory(directory: Path) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for node in PIPELINE:
        patch = _json(directory / "nodes" / f"{node}.json")
        state.update(patch)
    return state


def context_hash(state: Mapping[str, Any], *, draft: Mapping[str, Any] | None = None) -> str:
    body = {key: state.get(key) for key in _CONTEXT}
    for name in ("keyframes", "videos"):
        body[name] = [
            item
            for item in _rows(state.get(name))
            if isinstance(item, dict) and item.get("selected") is True
        ]
    body["saved_draft"] = dict(draft or {})
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def draft_context(project_id: str, media: str | Path | None = None) -> dict[str, Any]:
    """Content intent only. Layout/version counters are not render inputs."""

    root = project_path(project_id).resolve()
    if media is not None:
        path = Path(media).resolve()
        archived = path.parent / "draft-context.json"
        if path.is_relative_to(root / "versions") or path.is_relative_to(root / ".restore-staging"):
            if not archived.exists():
                return {}
            if not archived.resolve().is_relative_to(root):
                return {"invalid_saved_draft": True}
            try:
                saved = json.loads(archived.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {"invalid_saved_draft": True}
            return saved if isinstance(saved, dict) else {"invalid_saved_draft": True}
    path = root / "canvas.json"
    if not path.exists():
        return {}
    if not path.resolve().is_relative_to(root):
        return {"invalid_saved_draft": True}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"invalid_saved_draft": True}
    if not isinstance(raw, dict):
        return {"invalid_saved_draft": True}
    projection: dict[str, Any] = {}
    shots = raw.get("shots")
    if isinstance(shots, dict):
        edits = {}
        for shot_id, row in shots.items():
            if not isinstance(row, dict):
                continue
            values = {
                key: row[key]
                for key in ("narration", "prompt_suffix", "reference_upload_id")
                if key in row and row[key] is not None and (key == "narration" or row[key] != "")
            }
            if values:
                edits[shot_id] = values
        if edits:
            projection["shots"] = edits
    if raw.get("timeline_clips") is not None:
        projection["timeline_clips"] = raw["timeline_clips"]
    ui = {
        "position",
        "viewport",
        "selected",
        "expanded",
        "collapsed",
        "status",
        "progress",
        "error",
        "candidates",
        "outputs",
        "created_at",
        "updated_at",
        "regen_count",
    }
    semantic = [
        row
        for row in _rows(raw.get("edges"))
        if isinstance(row, dict)
        and isinstance(row.get("role"), str)
        and row["role"] in {"reference", "feeds_final", "text"}
    ]
    if any(not isinstance(row.get(key), str) for row in semantic for key in ("source", "target")):
        return {"invalid_saved_draft": True}
    reached = {
        row["target"]
        for row in semantic
        if row["target"] == "final"
        or row["target"].startswith("shot:")
        or row["target"] in PIPELINE
    }
    while True:
        added = {row["source"] for row in semantic if row["target"] in reached} - reached
        if not added:
            break
        reached.update(added)
    nodes = []
    for node in _rows(raw.get("user_nodes")):
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("id"), str)
            or node["id"] not in reached
        ):
            continue
        data = node.get("data")
        nodes.append(
            {
                "id": node.get("id"),
                "kind": node.get("kind"),
                "data": {key: value for key, value in data.items() if key not in ui}
                if isinstance(data, dict)
                else {},
            }
        )
    if nodes:
        projection["user_nodes"] = sorted(nodes, key=lambda node: str(node["id"]))
    edges = [
        {
            key: row.get(key)
            for key in ("source", "target", "source_handle", "target_handle", "role")
        }
        for row in semantic
        if row["target"] in reached
    ]
    if edges:
        projection["semantic_edges"] = sorted(
            edges, key=lambda row: json.dumps(row, sort_keys=True)
        )
    return projection


def invalidate_media_cache() -> None:
    """Call after a render/restore; stat-key changes also invalidate naturally."""

    _inspect.cache_clear()


def readiness(
    snapshot: Mapping[str, Any],
    state: Mapping[str, Any] | None = None,
    media: str | Path | None = None,
) -> dict[str, Any]:
    project_id = str(snapshot.get("project_id") or "")
    scope_valid = _valid_project_scope(project_id)
    state = (
        dict(state)
        if state is not None
        else (state_from_directory(project_path(project_id)) if scope_valid else {})
    )
    raw = (
        str(media)
        if media is not None
        else (
            snapshot.get("preview_path") or snapshot.get("deliverable") or state.get("deliverable")
        )
    )
    located = contained_file(project_id, raw) if scope_valid else None
    draft = draft_context(project_id, located) if scope_valid else {}
    info = _media(project_id, located)
    evidence = evidence_for(project_id, info.get("media_hash", ""))
    provenance = _provenance(state, evidence)
    reasons: list[dict[str, str]] = []

    def reject(code: str, message: str) -> None:
        reasons.append({"code": code, "message": message})

    if not info.get("preview_available"):
        reject("media_unavailable", "成片文件缺失、不可读取或无法解码")
    elif (
        info.get("codec") != "h264"
        or abs(info.get("fps", 0) - FPS) > 0.05
        or "mp4" not in str(info.get("container", "")).split(",")
    ):
        reject("delivery_format_unverified", "正式成片需符合H.264 MP4与30fps导出要求")
    if provenance != "live":
        reject("media_not_live", "素材含模拟内容或来源尚未核验")
    if not evidence:
        reject("final_review_missing", "尚无绑定这份成片文件的真实终审证据")
    else:
        if evidence.get("schema_version") != 1 or evidence.get("producer") != "n16_final_review":
            reject("evidence_invalid", "终审记录格式或来源无效")
        if evidence.get("project_id") != project_id or evidence.get("media_hash") != info.get(
            "media_hash"
        ):
            reject("media_hash_mismatch", "终审记录与当前成片文件不一致")
        if evidence.get("enterprise_id") != snapshot.get("enterprise_id") or not snapshot.get(
            "enterprise_id"
        ):
            reject("evidence_owner_mismatch", "终审授权与当前企业不一致")
        if evidence.get("context_hash") != context_hash(state, draft=draft):
            reject("review_context_changed", "脚本、品牌或授权资料已改变，需要重新核验")
        rendered = _render_evidence(project_id, info.get("media_hash"))
        if not (
            rendered.get("producer") == "n15_compose"
            and rendered.get("project_id") == project_id
            and rendered.get("media_hash") == info.get("media_hash")
            and rendered.get("context_hash") == context_hash(state, draft=draft)
            and rendered.get("context_hash") == evidence.get("context_hash")
        ):
            reject("draft_not_rendered", "当前内容草稿尚未渲染为这份成片，不能沿用旧审核")
        if draft.get("invalid_saved_draft"):
            reject("saved_draft_unreadable", "已保存的内容草稿无法读取，需要核验")
        _review_reasons(evidence, state, reject)
        _logo_reasons(evidence, state, reject)
        label = evidence.get("ai_label") or {}
        if not (
            isinstance(label, dict)
            and label.get("media_hash") == info.get("media_hash")
            and label.get("visual_verified") is True
            and label.get("metadata_verified") is True
            and isinstance(label.get("visual_method"), str)
            and label.get("visual_method") in {"ocr", "pixel_match", "human_pixel_review"}
        ):
            reject("ai_label_unverified", "AI显式标识与文件元数据尚未获得实际验证")
        _authorization_reasons(evidence, state, snapshot, reject)
        sources = evidence.get("sources") or {}
        records = _rows(sources.get("records")) if isinstance(sources, dict) else []
        if not (
            isinstance(sources, dict)
            and sources.get("media_hash") == info.get("media_hash")
            and sources.get("verified") is True
            and sources.get("complete") is True
            and records
            and all(
                isinstance(row, dict)
                and row.get("execution_mode") == "live"
                and row.get("evidence_ref")
                and isinstance(row.get("billing_status"), str)
                and row.get("billing_status") in {"settled", "not_billable"}
                for row in records
            )
        ):
            if provenance == "live":
                provenance = "unknown"
            reject("source_lineage_unverified", "素材来源与调用费用链尚未完整核验")
        else:
            from workers.workflow.source_evidence import verified_sources

            root = project_path(project_id).resolve()
            nodes = root / "nodes"
            if located and (
                Path(located).is_relative_to(root / "versions")
                or Path(located).is_relative_to(root / ".restore-staging")
            ):
                nodes = Path(located).parent / "nodes"
            try:
                journal_verified = verified_sources(
                    _source_store(), project_id, sources, state, nodes_directory=nodes
                )
            except Exception:
                journal_verified = False
            if not journal_verified:
                if provenance == "live":
                    provenance = "unknown"
                reject("source_journal_unverified", "真实来源或费用尚无匹配的服务端已结算调用记录")
    if classify_concept(state.get("concept")).degraded or snapshot.get("concept_degraded") is True:
        reject("concept_degraded", "创意仍为降级草稿，不能正式交付")
    if snapshot.get("revision_incomplete") is True:
        reject("revision_incomplete", "本次修改仍有未完成的镜头，保留上一版供预览")
    if info.get("media_hash") and snapshot.get("review_required_hash") == info["media_hash"]:
        reject(
            "review_required_after_release", "人工操作只允许继续生成，当前文件仍需重新完成真实核验"
        )
    passed = not reasons
    status = (
        "ready"
        if passed
        else (
            "unavailable"
            if not info.get("preview_available")
            else "preview"
            if provenance in {"mock", "mixed"}
            else "needs_verification"
        )
    )
    internal = False
    if not passed and info.get("preview_available"):
        from workers.compliance.moderation import internal_delivery

        if internal_delivery():
            status = "internal"
            internal = True
    return {
        **info,
        "delivery_status": status,
        "media_provenance": provenance,
        "quality_pass": passed,
        "internal_only": internal,
        "reasons": reasons,
    }


def record_delivery_evidence(
    project_id: str,
    media: str | Path,
    final_review: Mapping[str, Any],
    *,
    state: Mapping[str, Any],
    media_provenance: str,
    logo_evidence: Mapping[str, Any],
    ai_label_evidence: Mapping[str, Any],
    authorization_evidence: Mapping[str, Any],
    source_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Internal writer, never expose as an HTTP request-body endpoint.

    Review/verification activities supply their measured evidence. This does
    not convert a mock review into a real one, nor infer pixel checks from
    overlay names. Failed reviews may be recorded but will never pass readiness.
    """

    from workers.workflow.versions import atomic_write

    if not _valid_project_scope(project_id):
        raise ValueError("delivery evidence requires its own authorized project directory")
    snapshot = _json(project_path(project_id) / "project.json")
    located = contained_file(project_id, str(media))
    info = _media(project_id, located)
    if not info.get("preview_available"):
        raise ValueError("delivery evidence requires a decodable project media file")
    digest = info["media_hash"]
    rendered = _render_evidence(project_id, digest)
    draft = rendered.get("draft_context") if isinstance(rendered.get("draft_context"), dict) else {}
    label = dict(ai_label_evidence)
    try:
        metadata = read_aigc(Path(located))
        metadata_ok = (
            metadata.get("ContentProducer") != PLACEHOLDER_PRODUCER
            and hmac_key() != TEST_HMAC_KEY.encode()
        )
    except (OSError, ValueError, RuntimeError):
        metadata_ok = False
    label["metadata_verified"] = metadata_ok
    record = {
        "schema_version": 1,
        "producer": "n16_final_review",
        "project_id": project_id,
        "enterprise_id": snapshot.get("enterprise_id"),
        "media_hash": digest,
        "context_hash": context_hash(state, draft=draft),
        "draft_context": draft,
        "created_at": time.time(),
        "media_provenance": media_provenance
        if isinstance(media_provenance, str) and media_provenance in _KINDS
        else "unknown",
        "final_review": dict(final_review),
        "logo": dict(logo_evidence),
        "ai_label": label,
        "authorization": dict(authorization_evidence),
        "sources": dict(source_evidence or {}),
    }
    root = project_path(project_id).resolve()
    # An attempt to review an unrendered input set must not destroy the
    # previous immutable version's valid evidence for these same movie bytes.
    unmatched_render = rendered.get("context_hash") != record["context_hash"]
    name = f"{digest}-{uuid.uuid4().hex}.json" if unmatched_render else f"{digest}.json"
    folder = "review-attempts" if unmatched_render else "reviews"
    target = (root / folder / name).resolve()
    if not target.is_relative_to(root):
        raise ValueError("delivery evidence must remain inside its project")
    atomic_write(
        target,
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode() + b"\n",
    )
    if not unmatched_render and snapshot.get("review_required_hash") == digest:
        verified = readiness({**snapshot, "review_required_hash": None}, state, media)
        if verified["quality_pass"]:
            from workers.workflow.store import update_snapshot

            update_snapshot(project_id, review_required_hash=None)
    return record


def record_render_context(
    project_id: str,
    media: str | Path,
    state: Mapping[str, Any],
    *,
    applied_draft_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Internal N15 hook, after rendering with the actual inputs supplied.

    A saved canvas is not an execution graph. Its content is included only
    when a render consumer explicitly supplied the projection it applied.
    """

    from workers.workflow.versions import atomic_write

    if not _valid_project_scope(project_id):
        raise ValueError("render context requires its own authorized project directory")
    located = contained_file(project_id, str(media))
    inspected = _media(project_id, located)
    if not inspected.get("preview_available"):
        raise ValueError("render context requires a decodable project media file")
    draft = dict(applied_draft_context or {})
    _validate_applied_draft(state, draft)
    digest = inspected["media_hash"]
    record = {
        "producer": "n15_compose",
        "project_id": project_id,
        "media_hash": digest,
        "context_hash": context_hash(state, draft=draft),
        "draft_context": draft,
    }
    root = project_path(project_id).resolve()
    destination = (root / "render-evidence" / f"{digest}.json").resolve()
    if not destination.is_relative_to(root):
        raise ValueError("render context must remain inside its project")
    atomic_write(
        destination, json.dumps(record, ensure_ascii=False, sort_keys=True).encode() + b"\n"
    )
    return record


def _render_evidence(project_id: str, digest: Any) -> dict[str, Any]:
    if (
        not valid_project_id(project_id)
        or not isinstance(digest, str)
        or not _HASH.fullmatch(digest)
    ):
        return {}
    root = project_path(project_id).resolve()
    path = (root / "render-evidence" / f"{digest}.json").resolve()
    return _json(path) if path.is_relative_to(root) else {}


def _validate_applied_draft(state: Mapping[str, Any], draft: Mapping[str, Any]) -> None:
    # N15 does not consume CanvasDoc.timeline_clips or the user-node graph yet.
    # Do not allow a future caller to certify these merely by passing a dict.
    if not draft:
        return
    if set(draft) - {"shots"} or not isinstance(draft.get("shots"), dict):
        raise ValueError(
            "saved clips, references and graph parameters have no verified render consumer"
        )
    script = state.get("script")
    shots = (
        {row.get("shot_id"): row for row in _rows(script.get("shots")) if isinstance(row, dict)}
        if isinstance(script, dict)
        else {}
    )
    takes = {
        row.get("shot_id"): row for row in _rows(state.get("voiceovers")) if isinstance(row, dict)
    }
    from workers.nodes.n06_voiceover.audio import character_error_rate

    for shot_id, edit in draft["shots"].items():
        if not isinstance(edit, dict) or set(edit) != {"narration"}:
            raise ValueError(
                "saved shot references and prompt edits have no verified render consumer"
            )
        text = edit["narration"]
        take = takes.get(shot_id)
        if not (
            isinstance(text, str)
            and text.strip()
            and shots.get(shot_id, {}).get("voiceover") == text
            and take
            and character_error_rate(text, str(take.get("transcript") or "")) < 0.02
        ):
            raise ValueError("saved narration does not match the supplied rendered script and take")


def evidence_for(project_id: str, digest: str) -> dict[str, Any]:
    if (
        not valid_project_id(project_id)
        or not isinstance(digest, str)
        or not _HASH.fullmatch(digest)
    ):
        return {}
    root = project_path(project_id).resolve()
    path = (root / "reviews" / f"{digest}.json").resolve()
    if not path.is_relative_to(root):
        return {}
    return _json(path)


def _json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _media(project_id: str, located: str | None) -> dict[str, Any]:
    if not located:
        return {"preview_available": False, "media_hash": None, "media_path": None}
    try:
        stamp = Path(located).stat()
        signature = (
            stamp.st_dev,
            stamp.st_ino,
            stamp.st_size,
            stamp.st_mtime_ns,
            stamp.st_ctime_ns,
        )
        return dict(_inspect(project_id, located, signature))
    except (OSError, ValueError):
        return {"preview_available": False, "media_hash": None, "media_path": None}


@lru_cache(maxsize=128)
def _inspect(project_id: str, located: str, signature: tuple[int, ...]) -> dict[str, Any]:
    del project_id  # It intentionally remains part of the authorization-scoped cache key.
    path = Path(located)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    result: dict[str, Any] = {
        "preview_available": False,
        "media_hash": digest.hexdigest(),
        "media_path": located,
    }
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        return result
    try:
        probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-format_whitelist",
                "mov,matroska,webm,avi",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                located,
            ],
            capture_output=True,
            timeout=15,
            check=False,
        )
        data = json.loads(probe.stdout)
        videos = [item for item in data.get("streams", []) if item.get("codec_type") == "video"]
        if probe.returncode or not videos or float(data.get("format", {}).get("duration", 0)) <= 0:
            return result
        decoded = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-xerror",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                located,
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=90,
            check=False,
        )
        after = path.stat()
        stable = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) == signature
        result["preview_available"] = decoded.returncode == 0 and stable
        result["media_size"] = signature[2]
        result["duration_s"] = float(data.get("format", {}).get("duration", 0))
        result["container"] = str(data.get("format", {}).get("format_name", ""))
        result["codec"] = videos[0].get("codec_name")
        result["fps"] = float(Fraction(videos[0].get("avg_frame_rate") or "0/1"))
        result["width"] = videos[0].get("width")
        result["height"] = videos[0].get("height")
    except (OSError, ValueError, ZeroDivisionError, subprocess.TimeoutExpired):
        return result
    return result


def _provenance(state: Mapping[str, Any], evidence: Mapping[str, Any]) -> str:
    sources = []
    for value in (
        state.get("execution_mode"),
        state.get("media_provenance"),
        state.get("audio_provenance"),
        evidence.get("media_provenance"),
    ):
        if value is not None:
            sources.append(value if isinstance(value, str) and value in _KINDS else "unknown")
    track = state.get("audio_track")
    if isinstance(track, dict):
        sources.append(track.get("provenance", "unknown"))
    for take in _rows(state.get("voiceovers")):
        if isinstance(take, dict):
            sources.append(
                "mock"
                if str(take.get("uri", "")).startswith("mock://")
                else take.get("provenance", "unknown")
            )
    for candidate in [*_rows(state.get("keyframes")), *_rows(state.get("videos"))]:
        if not isinstance(candidate, dict) or candidate.get("selected") is False:
            continue
        params = candidate.get("params") or {}
        mock = params.get("mock") if isinstance(params, dict) else None
        if isinstance(params, dict) and "execution_mode" in params:
            sources.append(params["execution_mode"])
        if str(candidate.get("model", "")).startswith("mock") or str(
            candidate.get("uri", "")
        ).startswith("mock://"):
            mock = True
        sources.append("mock" if mock is True else "live" if mock is False else "unknown")
    timeline = state.get("timeline") or {}
    if isinstance(timeline, dict) and any(
        isinstance(clip, dict) and clip.get("placeholder") is True
        for clip in _rows(timeline.get("clips"))
    ):
        sources.append("mock")
    lineage = evidence.get("sources") or {}
    if isinstance(lineage, dict):
        sources.extend(
            row.get("execution_mode", "unknown")
            for row in _rows(lineage.get("records"))
            if isinstance(row, dict)
        )
    safe = [item if isinstance(item, str) and item in _KINDS else "unknown" for item in sources]
    return combine_provenance(safe)


def _review_reasons(evidence: Mapping[str, Any], state: Mapping[str, Any], reject: Any) -> None:
    review = evidence.get("final_review") or {}
    if not isinstance(review, dict):
        review = {}
    if review.get("media_hash") != evidence.get("media_hash"):
        reject("review_media_hash_mismatch", "真实终审尚未绑定当前成片文件的精确校验值")
    if review.get("enterprise_id") != evidence.get("enterprise_id"):
        reject("review_owner_mismatch", "真实终审尚未绑定当前企业")
    try:
        report = QAReport.model_validate(review.get("qa"))
        passed = is_quality_pass(report)
    except ValidationError:
        passed = False
    if not (
        passed
        and review.get("live") is True
        and review.get("release") is True
        and review.get("visual_reviewed") is True
        and review.get("disposition") == "release"
        and not review.get("issues")
        and not review.get("decisions")
    ):
        reject("final_review_failed", "成片尚未通过真实终审或仍有未解决的问题")
    asr = review.get("asr") or {}
    if not (
        isinstance(asr, dict)
        and asr.get("mock") is False
        and asr.get("verified") is True
        and asr.get("heard_audio") is True
        and asr.get("failed") is False
    ):
        reject("audio_review_unverified", "成片音频尚未经过真实回听核验")
    for key in ("compliance", "narrative", "hook", "film_judge"):
        value = review.get(key) or {}
        flag = "passed" if key == "compliance" else "usable" if key == "film_judge" else "ok"
        if (
            not isinstance(value, dict)
            or value.get(flag) is not True
            or value.get("blocked") is True
            or value.get("block_reasons")
        ):
            reject(f"{key}_unverified", "内容安全、叙事或整片评审证据不完整")
    brand = review.get("brand") or {}
    if not isinstance(brand, dict) or any(
        brand.get(key) is not True for key in ("complete", "ai_label", "logo_pixels", "cta_pixels")
    ):
        reject("brand_review_unverified", "成片Logo、行动号召及AI标识尚未获得真实评审")
    script = state.get("script")
    expected = (
        {str(shot.get("shot_id")) for shot in _rows(script.get("shots")) if isinstance(shot, dict)}
        if isinstance(script, dict)
        else set()
    )
    rows = _rows(review.get("shots"))
    found = {str(row.get("shot_id")) for row in rows if isinstance(row, dict)}
    valid_rows = bool(rows) and all(
        isinstance(row, dict)
        and row.get("visual_reviewed") is True
        and not row.get("hard_fail")
        and not row.get("content")
        and not row.get("review_error")
        and isinstance(row.get("total"), int | float)
        and math.isfinite(row["total"])
        and row["total"] <= 10
        and row["total"] >= PASS_TOTAL
        for row in rows
    )
    if not expected or found != expected or len(rows) != len(expected) or not valid_rows:
        reject("shot_review_incomplete", "并非全部镜头都获得了真实合格评审")


def _logo_reasons(evidence: Mapping[str, Any], state: Mapping[str, Any], reject: Any) -> None:
    logo = evidence.get("logo") or {}
    digests = {
        str(item.get("spec", {}).get("source_sha256"))
        for item in _rows(state.get("elements"))
        if isinstance(item, dict)
        and item.get("kind") == "outro_logo"
        and isinstance(item.get("spec"), dict)
    }
    if not (
        state.get("logo_status") == "ready"
        and isinstance(logo, dict)
        and logo.get("status") == "ready"
        and logo.get("media_hash") == evidence.get("media_hash")
        and logo.get("pixels_verified") is True
        and _HASH.fullmatch(str(logo.get("source_sha256") or ""))
        and logo.get("source_sha256") in digests
    ):
        reject("logo_unverified", "真实品牌Logo及其源图像素尚未核验")


def _authorization_reasons(
    evidence: Mapping[str, Any], state: Mapping[str, Any], snapshot: Mapping[str, Any], reject: Any
) -> None:
    rights = evidence.get("authorization") or {}
    if not (
        isinstance(rights, dict)
        and rights.get("passed") is True
        and rights.get("enterprise_id") == snapshot.get("enterprise_id")
        and rights.get("media_hash") == evidence.get("media_hash")
        and rights.get("consent_verified") is True
        and rights.get("evidence_refs")
    ):
        reject("authorization_unverified", "商用授权或肖像声音授权尚未完成服务端核验")
        return
    try:
        records = [LicenseRecord.model_validate(item) for item in rights.get("records") or []]
    except ValidationError:
        records = []
    reason = incomplete_reason(records)
    current = today_shanghai()
    if not records or not any(row.kind == "font" for row in records):
        reason = "missing font license"
    summary = state.get("licensing_summary")
    saved_records = _rows(summary.get("records")) if isinstance(summary, dict) else []
    fields = ("record_id", "kind", "source", "license", "evidence_ref", "expires_on", "usage_scope")
    covered = [tuple(getattr(row, key) for key in fields) for row in records]
    if any(
        not isinstance(row, dict) or tuple(row.get(key) for key in fields) not in covered
        for row in saved_records
    ):
        reason = "missing or mismatched used-asset license"
    takes = [item for item in _rows(state.get("voiceovers")) if isinstance(item, dict)]
    kinds = {row.kind for row in records}
    if (
        takes
        and "voice" not in kinds
        or isinstance(state.get("audio_track"), dict)
        and "music" not in kinds
    ):
        reason = "missing voice or music license"
    for record in records:
        if record.source.startswith("hilatv-test-") or "internal-test" in record.usage_scope:
            reason = "mock test license"
        if record.expires_on.lower() == "none":
            continue
        try:
            if date.fromisoformat(record.expires_on) < current:
                reason = "expired license"
        except ValueError:
            reason = "invalid license expiry"
    if reason:
        reject("license_incomplete", "所用音乐、音效、字体或声音授权缺失、过期或仅供测试")
    # Recheck the current archive so revoked consent cannot survive a cached
    # media inspection or a historical final-review document.
    try:
        for take in takes:
            assert_voice_allowed(str(take.get("voice") or ""), snapshot.get("enterprise_id"))
        script = state.get("script")
        shots = _rows(script.get("shots")) if isinstance(script, dict) else []
        person_shots = [
            row
            for row in shots
            if isinstance(row, dict)
            and (
                "人物" in str(row.get("purpose", ""))
                or any(str(ref).startswith("person:") for ref in _rows(row.get("subject_refs")))
            )
        ]
        if person_shots:
            allowed = archive_people(snapshot.get("enterprise_id"))
            names = {person.person_id for person in allowed} | {person.role for person in allowed}
            for shot in person_shots:
                refs = [
                    str(ref).split(":", 1)[1]
                    for ref in _rows(shot.get("subject_refs"))
                    if str(ref).startswith("person:")
                ]
                if not names or any(ref not in names for ref in refs):
                    raise ConsentError("portrait consent unavailable")
    except (ConsentError, OSError, ValueError):
        reject("consent_unverified", "当前企业档案中的肖像或声音授权缺失或已撤回")


def _rows(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _source_store() -> Any:
    from gateway import get_gateway

    return get_gateway().store


def _valid_project_scope(project_id: str) -> bool:
    if not valid_project_id(project_id):
        return False
    try:
        return project_path(project_id).resolve() == project_root().resolve() / project_id
    except (OSError, ValueError):
        return False
