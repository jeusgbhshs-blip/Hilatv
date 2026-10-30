"""N16 final review. Frames and the transcript go through the gateway.

Hard-flaw shots produce one director decision each. A clean mock film is
released without another run. Live mode does not release a film the judge
did not actually score. Regeneration spends ``open_project_budget.try_take``
once per shot and nowhere else.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from gateway.constants import NO_RENDERED_TEXT
from workers.logging import log_event
from workers.media.packaging import ai_label_text
from workers.nodes.n16_final_review.qa import QAError, check
from workers.nodes.n16_final_review.sample import frames_by_shot, write_wav
from workers.nodes.n16_final_review.schema import (
    FilmIssue,
    N16FinalInput,
    NodeRequest,
    NodeResult,
    ShotWindow,
)
from workers.nodes.runtime import Deadline
from workers.qa.budget_store import open_project_budget
from workers.qa.director import MAX_REVIEWS, decide
from workers.qa.scores import PASS_TOTAL
from workers.qa.service import review_shot
from workers.schemas.asset import QAReport, QAScores
from workers.schemas.director import DecisionAction, DecisionTarget, DirectorDecision
from workers.schemas.label_lock import LabelLocked, walk_label_edits
from workers.schemas.script import Script, Shot
from workers.workflow.store import project_path, read_snapshot, update_snapshot

NODE = "n16_final_review"
_PROMPTS = Path(__file__).resolve().parent / "prompts"
_LOGO_KINDS = {"intro_logo", "outro_logo", "corner_logo"}
_CONTENT = frozenset(
    {
        "product_deform",
        "extra_text",
        "garbled_text",
        "face_collapse",
        "face_count",
        "face_inconsistent",
        "black_bar",
        "watermark",
        "low_resolution",
        "bad_composition",
        "flicker",
        "sensitive",
    }
)
_MODEL_PROBLEMS = frozenset(
    {"product_deform", "face_collapse", "face_count", "face_inconsistent", "flicker"}
)
_NEXT = (
    "kling-o3",
    "doubao-seedance-1-0-pro-250528",
    "doubao-seedream-4-0-250828",
    "mock-image",
)
_CLEAN_SCORES = {
    "product_fidelity": 9,
    "motion_quality": 8,
    "aesthetics": 8,
    "prompt_match": 9,
    "artifact_free": 9,
}


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 180.0,
    max_attempts: int = 2,
    gateway: Any | None = None,
) -> NodeResult:
    body = dict(raw)
    payload = dict(body.get("payload") or {})
    payload.pop("enterprise_id", None)
    body["payload"] = payload
    request = NodeRequest.model_validate(body)
    N16FinalInput.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway if gateway is not None else _default_gateway()
    deadline = Deadline(timeout_s, node=NODE)
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            deadline.check()
            result = _execute(request, gateway=gateway, deadline=deadline)
            check(result)
        except QAError as exc:
            if not exc.retryable:
                raise
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=request.shot_id,
                attempt=attempt,
                error=str(exc),
            )
            continue
        return result
    message = f"n16_final_review failed after {max_attempts} attempts: {last_error}"
    raise QAError(message) from last_error


def _execute(request: NodeRequest, *, gateway: Any, deadline: Deadline) -> NodeResult:
    payload = N16FinalInput.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=request.attempt,
    )
    try:
        walk_label_edits(request.payload)
        if payload.instruction:
            walk_label_edits(payload.instruction)
    except LabelLocked as exc:
        raise QAError(str(exc)) from exc
    film = _contained(request.project_id, payload.film_path)
    enterprise_id = _enterprise_id(request.project_id)
    spans = [(shot.shot_id, shot.start_s, shot.end_s) for shot in payload.shots]
    try:
        grouped = frames_by_shot(film, spans)
        wav, heard = write_wav(film, film.parent / "n16-audio.wav")
    except Exception as exc:
        raise QAError(f"could not read the film: {exc}", retryable=True) from exc
    transcript, asr_mock = _transcribe(
        gateway,
        wav,
        request=request,
        reference=_reference(payload),
    )
    _judge_film(
        gateway,
        payload,
        transcript=transcript,
        request=request,
    )
    compliance = _compliance(
        request,
        payload,
        gateway=gateway,
        enterprise_id=enterprise_id,
        transcript=transcript,
        film=film,
    )
    deadline.check()
    shot_rows, issues = _score_shots(
        request,
        payload,
        grouped,
        gateway=gateway,
    )
    brand = _brand(payload.elements)
    narrative, hook, story_issues = _story(payload.script, payload.shots)
    issues.extend(story_issues)
    issues.extend(_brand_issues(brand, payload.shots))
    issues.extend(_compliance_issues(compliance, payload.script))
    if not brand["ai_label"]:
        issues.append(
            FilmIssue(
                shot_id=None,
                code="missing_ai_label",
                kind="compliance",
                detail="成片缺少显式标识「AI生成」，不能去掉这一层",
            )
        )
    decisions, taken, refused = _decisions(
        request,
        payload,
        shot_rows,
        gateway=gateway,
    )
    for shot_id in refused:
        issues.append(
            FilmIssue(
                shot_id=shot_id,
                code="budget_exhausted",
                kind="review",
                detail="项目重生次数已用完，这一镜不再生成",
            )
        )
    live = _live()
    reviewed = bool(shot_rows) and all(row["visual_reviewed"] is True for row in shot_rows)
    sampled = all(row["frames"] > 0 for row in shot_rows)
    asr_verified = heard and not asr_mock
    content_ids = {item.shot_id for item in issues if item.kind == "hard_flaw"}
    compliance_ok = compliance.get("passed") is True and brand["ai_label"]
    live_gap = live and (not reviewed or not asr_verified)
    if live_gap and not content_ids:
        issues.append(
            FilmIssue(
                shot_id=None,
                code="judge_unavailable",
                kind="review",
                detail="终审没有看过成片，不能放行",
            )
        )
    release = (
        not content_ids
        and not refused
        and brand["complete"]
        and narrative["ok"]
        and hook["ok"]
        and compliance_ok
        and sampled
        and not live_gap
    )
    blocking = (
        not brand["complete"]
        or not brand["ai_label"]
        or not narrative["ok"]
        or not hook["ok"]
        or not compliance_ok
        or not sampled
        or bool(refused)
        or (live_gap and not content_ids)
    )
    if release:
        disposition = "release"
    elif content_ids and decisions and not blocking:
        disposition = "redo"
    else:
        disposition = "hold"
    report = _film_report(shot_rows, issues, reviewed=reviewed)
    if disposition == "hold":
        _hold(request.project_id, issues)
    body = {
        "total": report.total,
        "total_source": "vlm" if reviewed else "rules",
        "vlm_total": report.total if reviewed else "未测",
        "visual_reviewed": reviewed,
        "release": release,
        "disposition": disposition,
        "live": live,
        "issues": [item.model_dump(mode="json") for item in issues],
        "decisions": [item.model_dump(mode="json") for item in decisions],
        "shots": shot_rows,
        "brand": brand,
        "narrative": narrative,
        "hook": hook,
        "compliance": {
            "passed": compliance.get("passed") is True,
            "blocked": compliance.get("blocked") is True,
            "block_reasons": list(compliance.get("block_reasons") or []),
            "moderation": compliance.get("moderation"),
            "extreme_words": list(compliance.get("extreme_words") or []),
        },
        "asr": {"mock": asr_mock, "verified": asr_verified, "heard_audio": heard},
        "enterprise_id": enterprise_id,
        "budget_taken": taken,
        "qa": report.model_dump(mode="json"),
    }
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=request.attempt,
        release=release,
        disposition=disposition,
        issues=len(issues),
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        attempt=request.attempt,
        payload=body,
    )


def _score_shots(
    request: NodeRequest,
    payload: N16FinalInput,
    grouped: dict[str, list[Any]],
    *,
    gateway: Any,
) -> tuple[list[dict[str, Any]], list[FilmIssue]]:
    script = {shot.shot_id: shot for shot in payload.script.shots}
    rows: list[dict[str, Any]] = []
    issues: list[FilmIssue] = []
    for window in payload.shots:
        frames = grouped.get(window.shot_id) or []
        shot = script.get(window.shot_id)
        if not frames:
            report = QAReport(
                scores=QAScores(
                    product_fidelity=0,
                    motion_quality=0,
                    aesthetics=0,
                    prompt_match=0,
                    artifact_free=0,
                ),
                hard_fail=["not_reviewed"],
                total=0,
                evaluator="not-reviewed",
                notes="not_reviewed; media=missing; vlm=未测; quality_pass=false",
                visual_reviewed=False,
            )
        else:
            report = review_shot(
                {
                    "project_id": request.project_id,
                    "shot_id": window.shot_id,
                    "node": NODE,
                    "purpose": shot.purpose if shot else "产品镜头",
                    "visual": shot.visual if shot else "画面没有文字",
                    "voiceover": shot.voiceover if shot else "",
                    "shot_type": shot.camera if shot else "locked_off",
                    "generation_mode": shot.generation_mode.value if shot else "image_to_video",
                    "anchor_uri": window.anchor_uri or "",
                    "expected_faces": window.expected_faces,
                },
                gateway=gateway,
                frames=frames,
            )
        codes = [code for code in report.hard_fail if code in _CONTENT]
        for code in codes:
            issues.append(
                FilmIssue(
                    shot_id=window.shot_id,
                    code=code,
                    kind="hard_flaw",
                    detail=f"{window.shot_id} {code}",
                )
            )
        rows.append(
            {
                "shot_id": window.shot_id,
                "visual_reviewed": report.visual_reviewed is True,
                "hard_fail": list(report.hard_fail),
                "content": codes,
                "total": report.total,
                "frames": len(frames),
                "model": window.model,
            }
        )
    return rows, issues


def _decisions(
    request: NodeRequest,
    payload: N16FinalInput,
    rows: list[dict[str, Any]],
    *,
    gateway: Any,
) -> tuple[list[DirectorDecision], int, list[str]]:
    script = {shot.shot_id: shot for shot in payload.script.shots}
    decisions: list[DirectorDecision] = []
    taken = 0
    refused: list[str] = []
    for row in rows:
        if not row["content"]:
            continue
        shot = script.get(row["shot_id"])
        report = _shot_report(row)
        # The model may only choose between the two redo actions. Shot id,
        # attempt cap, and sensitive / fallback stay on the local policy.
        chosen = decide(
            report,
            node="N10",
            shot_id=row["shot_id"],
            attempt=request.attempt,
            model=str(row.get("model") or ""),
            prompt=shot.visual if shot else "",
            gateway=gateway,
            project_id=request.project_id,
            budget=None,
        )
        action = _action_for(row["content"], attempt=request.attempt)
        if action in {DecisionAction.regenerate, DecisionAction.switch_model} and chosen.action in {
            DecisionAction.regenerate,
            DecisionAction.switch_model,
        }:
            action = chosen.action
        left = max(0, MAX_REVIEWS - request.attempt)
        decision = DirectorDecision(
            action=action,
            target=DecisionTarget(node="N10", shot_id=row["shot_id"]),
            reason=_reason(action, row["content"]),
            changes=_changes(action, str(row.get("model") or "")),
            max_attempts_left=left if action is not DecisionAction.fallback else 0,
        )
        decision = DirectorDecision.model_validate(decision.model_dump())
        if decision.action in {DecisionAction.regenerate, DecisionAction.switch_model}:
            if not open_project_budget(request.project_id).try_take():
                refused.append(row["shot_id"])
                continue
            taken += 1
        decisions.append(decision)
    return decisions, taken, refused


def _action_for(codes: list[str], *, attempt: int) -> DecisionAction:
    if "sensitive" in codes:
        return DecisionAction.ask_user
    if attempt >= MAX_REVIEWS:
        return DecisionAction.fallback
    if any(code in _MODEL_PROBLEMS for code in codes):
        return DecisionAction.switch_model
    return DecisionAction.regenerate


def _reason(action: DecisionAction, codes: list[str]) -> str:
    listed = "、".join(codes)
    if action is DecisionAction.ask_user:
        return f"疑似敏感内容，需要人工确认（{listed}）"
    if action is DecisionAction.fallback:
        return f"已满 {MAX_REVIEWS} 次仍不合格，改用 AI 降级生成（{listed}）"
    if action is DecisionAction.switch_model:
        return f"硬伤镜头更换模型后重生（{listed}）"
    return f"硬伤镜头调整提示词后重生（{listed}）"


def _changes(action: DecisionAction, model: str) -> dict[str, Any]:
    if action is DecisionAction.ask_user:
        return {
            "question": "画面可能包含敏感内容，确认后才能继续。只重新生成 AI 画面。",
            "source": "ai_generated",
        }
    if action is DecisionAction.fallback:
        return {
            "plan": "ai_fallback",
            "source": "ai_generated",
            "prompt_suffix": NO_RENDERED_TEXT,
        }
    changes: dict[str, Any] = {
        "source": "ai_generated",
        "prompt_suffix": NO_RENDERED_TEXT,
        "candidates": 4,
    }
    if action is DecisionAction.switch_model:
        changes["model"] = _next_model(model)
        changes["motion_strength"] = "low"
    return changes


def _next_model(model: str) -> str:
    if model in _NEXT:
        return _NEXT[(_NEXT.index(model) + 1) % len(_NEXT)]
    return _NEXT[0]


def _shot_report(row: dict[str, Any]) -> QAReport:
    """A report the director can read. Scores stay at 0 until a judge saw the frame."""

    notes = "vlm=未测; quality_pass=false" if not row["visual_reviewed"] else "quality_pass=false"
    if row["total"] >= PASS_TOTAL and row["visual_reviewed"] and not row["content"]:
        notes = "quality_pass=true"
    return QAReport(
        scores=QAScores(
            product_fidelity=2 if row["content"] else 8,
            motion_quality=2 if row["content"] else 8,
            aesthetics=2 if row["content"] else 8,
            prompt_match=2 if row["content"] else 8,
            artifact_free=2 if row["content"] else 8,
        ),
        hard_fail=list(row["content"]) or list(row["hard_fail"]),
        total=4.0 if row["content"] else float(row["total"] or 0),
        evaluator="n16-final-review",
        notes=notes,
        visual_reviewed=row["visual_reviewed"] is True,
    )


def _film_report(
    rows: list[dict[str, Any]],
    issues: list[FilmIssue],
    *,
    reviewed: bool,
) -> QAReport:
    codes = [item.code for item in issues if item.kind == "hard_flaw"]
    if codes:
        scores = {name: 4 for name in _CLEAN_SCORES}
        total = 4.0
    elif reviewed:
        totals = [float(row["total"]) for row in rows] or [0.0]
        total = round(sum(totals) / len(totals), 1)
        scores = dict(_CLEAN_SCORES)
    else:
        scores = dict(_CLEAN_SCORES)
        total = round(sum(scores.values()) / len(scores), 1)
    note = "终审"
    if not reviewed:
        note = f"{note}; vlm=未测; quality_pass=false; total_source=rules"
    elif codes:
        note = f"{note}; quality_pass=false"
    else:
        note = f"{note}; quality_pass=true"
    return QAReport(
        scores=QAScores.model_validate(scores),
        hard_fail=list(dict.fromkeys(codes)),
        total=total,
        evaluator="vlm-judge-v1" if reviewed else "n16-final-review",
        notes=note,
        visual_reviewed=reviewed,
        judges_used=2 if reviewed else 0,
        degraded=False,
    )


def _brand(elements: list[dict[str, Any]]) -> dict[str, bool]:
    label = ai_label_text()
    logo = False
    cta = False
    marked = False
    for item in elements:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        text = str(item.get("text") or "")
        if kind in _LOGO_KINDS or kind.endswith("_logo"):
            logo = True
        if "cta" in kind:
            cta = True
        if kind == "ai_label" or label in text:
            marked = True
    return {"logo": logo, "cta": cta, "ai_label": marked, "complete": logo and cta}


def _brand_issues(brand: dict[str, bool], shots: list[ShotWindow]) -> list[FilmIssue]:
    found: list[FilmIssue] = []
    if brand["logo"] and brand["cta"]:
        return found
    anchor = shots[-1].shot_id if shots else None
    if not brand["logo"]:
        found.append(
            FilmIssue(
                shot_id=anchor,
                code="missing_logo",
                kind="brand",
                detail="成片没有 Logo 叠层",
            )
        )
    if not brand["cta"]:
        found.append(
            FilmIssue(
                shot_id=anchor,
                code="missing_cta",
                kind="brand",
                detail="成片没有 CTA 叠层",
            )
        )
    return found


def _story(
    script: Script,
    shots: list[ShotWindow],
) -> tuple[dict[str, Any], dict[str, Any], list[FilmIssue]]:
    ordered = sorted(shots, key=lambda item: (item.start_s, item.shot_id))
    by_id = {shot.shot_id: shot for shot in script.shots}
    film_ids = [item.shot_id for item in ordered]
    script_ids = [shot.shot_id for shot in script.shots]
    present = all(shot_id in by_id for shot_id in film_ids)
    narrative_ok = present and _same_order(film_ids, script_ids)
    first = ordered[0]
    opening = by_id.get(first.shot_id)
    hook_ok = bool(opening and (opening.purpose.strip() or opening.voiceover.strip()))
    issues: list[FilmIssue] = []
    if not narrative_ok:
        issues.append(
            FilmIssue(
                shot_id=first.shot_id,
                code="narrative_gap",
                kind="narrative",
                detail="镜头顺序和脚本对不上",
            )
        )
    if not hook_ok:
        issues.append(
            FilmIssue(
                shot_id=first.shot_id,
                code="hook_weak",
                kind="hook",
                detail="开场镜头没有目的也没有旁白",
            )
        )
    narrative = {"ok": narrative_ok, "source": "structural", "vlm": "未测"}
    hook = {"ok": hook_ok, "source": "structural", "vlm": "未测"}
    return narrative, hook, issues


def _same_order(film_ids: list[str], script_ids: list[str]) -> bool:
    positions = []
    for shot_id in film_ids:
        if shot_id not in script_ids:
            return False
        positions.append(script_ids.index(shot_id))
    return positions == sorted(positions)


def _compliance_issues(compliance: dict[str, Any], script: Script) -> list[FilmIssue]:
    found: list[FilmIssue] = []
    words = [str(item) for item in compliance.get("extreme_words") or []]
    if words:
        shot_id = _word_shot(script, words)
        found.append(
            FilmIssue(
                shot_id=shot_id,
                code="extreme_words",
                kind="compliance",
                detail="极限词：" + "、".join(words),
            )
        )
    for reason in compliance.get("block_reasons") or []:
        text = str(reason)
        if text.startswith("extreme words"):
            continue
        found.append(
            FilmIssue(
                shot_id=None,
                code="content_safety",
                kind="compliance",
                detail=text,
            )
        )
    return found


def _word_shot(script: Script, words: list[str]) -> str | None:
    for shot in script.shots:
        blob = f"{shot.purpose}\n{shot.visual}\n{shot.voiceover}"
        if any(word in blob for word in words):
            return shot.shot_id
    return None


def _compliance(
    request: NodeRequest,
    payload: N16FinalInput,
    *,
    gateway: Any,
    enterprise_id: str | None,
    transcript: str,
    film: Path,
) -> dict[str, Any]:
    from workers.nodes.n16_review.node import run as compliance_run
    from workers.nodes.n16_review.qa import QAError as ComplianceError

    texts = [item for item in payload.texts if item]
    if transcript:
        texts.append(transcript)
    body = {
        "stage": "output",
        "brief": payload.brief.model_dump(mode="json"),
        "script": payload.script.model_dump(mode="json"),
        "brand_kit": payload.brand_kit.model_dump(mode="json") if payload.brand_kit else None,
        "enterprise_id": enterprise_id,
        "texts": texts,
        "media_paths": [str(film)],
        "licensing": (
            payload.licensing.model_dump(mode="json") if payload.licensing is not None else None
        ),
    }
    try:
        result = compliance_run(
            {"project_id": request.project_id, "payload": body, "attempt": request.attempt},
            gateway=gateway,
        )
    except ComplianceError as exc:
        raise QAError(str(exc), retryable=exc.retryable) from exc
    return result.payload


def _transcribe(
    gateway: Any,
    wav: Path,
    *,
    request: NodeRequest,
    reference: str,
) -> tuple[str, bool]:
    asr = getattr(gateway, "asr", None)
    if not callable(asr):
        raise QAError("asr gateway is missing", retryable=True)
    try:
        raw = asr(
            str(wav),
            project_id=request.project_id,
            node=NODE,
            shot_id=request.shot_id,
            attempt=request.attempt,
            language="zh",
            params={"reference_text": reference},
        )
    except Exception as exc:
        raise QAError(f"asr failed: {exc}", retryable=True) from exc
    if not isinstance(raw, dict):
        return "", True
    text = raw.get("text")
    return (text if isinstance(text, str) else ""), bool(raw.get("mock"))


def _judge_film(
    gateway: Any,
    payload: N16FinalInput,
    *,
    transcript: str,
    request: NodeRequest,
) -> None:
    judge = getattr(gateway, "judge", None)
    if not callable(judge):
        raise QAError("judge gateway is missing", retryable=True)
    env = Environment(
        loader=FileSystemLoader(_PROMPTS),
        autoescape=False,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    shots = []
    script = {shot.shot_id: shot for shot in payload.script.shots}
    for window in payload.shots:
        shot: Shot | None = script.get(window.shot_id)
        shots.append(
            {
                "shot_id": window.shot_id,
                "start_s": window.start_s,
                "end_s": window.end_s,
                "purpose": shot.purpose if shot else "",
                "visual": shot.visual if shot else "",
            }
        )
    prompt = env.get_template("judge.j2").render(
        shots=shots,
        transcript=transcript or "（无转写）",
        rule_notes="pixel rules run per shot; this call is the film-level review",
    )
    try:
        judge(
            prompt,
            project_id=request.project_id,
            node=NODE,
            shot_id=request.shot_id,
            attempt=request.attempt,
            seed=17,
        )
    except Exception as exc:
        log_event(
            "qa_judge_failed",
            project_id=request.project_id,
            node=NODE,
            shot_id=request.shot_id,
            attempt=request.attempt,
            error=str(exc)[:300],
        )


def _reference(payload: N16FinalInput) -> str:
    if payload.reference_text:
        return payload.reference_text
    lines = [shot.voiceover.strip() for shot in payload.script.shots if shot.voiceover.strip()]
    return " ".join(lines)


def _enterprise_id(project_id: str) -> str | None:
    snapshot = read_snapshot(project_id)
    if not isinstance(snapshot, dict) or "enterprise_id" not in snapshot:
        return None
    value = snapshot.get("enterprise_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _hold(project_id: str, issues: list[FilmIssue]) -> None:
    if read_snapshot(project_id) is None:
        return
    detail = "、".join(item.code for item in issues[:6]) or "终审未放行"
    update_snapshot(
        project_id,
        status="needs_human_review",
        phase="待人工复核",
        node=NODE,
        message=f"成片终审未放行：{detail}",
        paused=True,
        deliverable=None,
    )
    log_event(
        "human_review_held",
        project_id=project_id,
        node=NODE,
        attempt=1,
        shots=len({item.shot_id for item in issues if item.shot_id}),
    )


def _contained(project_id: str, raw: str) -> Path:
    root = project_path(project_id, create=True).resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise QAError("film path must stay inside the project directory")
    if not resolved.is_file():
        raise QAError("film file is missing")
    return resolved


def _live() -> bool:
    return os.getenv("HILATV_LIVE", "0").strip() == "1"


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
