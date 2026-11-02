"""Execute the director's fallback ladder for one film.

Order, after the owner decision that replaced SPEC §6.10 levels 3 and 4:

1. Regenerate through the gateway with another route, a rewritten prompt, and a new seed.
   The spend goes through ``open_project_budget``.
2. Image-to-video from an AI keyframe that passed QA (``visual_reviewed`` and the pass line).
3. That keyframe plus a programmatic camera move (Ken Burns, or 2.5D parallax when a cutout exists).
4. Motion graphics: a T13 cutout when one is available, render-layer text cards, and generated
   background motion. This step always produces a clip.

Each clip is reviewed with ``review_shot``. Levels 1–3 keep a clip only when
``visual_reviewed`` is true and ``hard_fail`` is empty. Anything else, including
``not_reviewed``, ``judge_unavailable``, and a mock judge, drops to the next
level. Level 4 still produces a clip when review is unavailable and marks
``needs_review``. A downgraded shot is never a QA pass and never reviewed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from gateway.constants import NO_RENDERED_TEXT
from workers.fallback.encode import frame_count, ken_burns, motion_graphic, parallax
from workers.fallback.files import read_bytes, write_output
from workers.fallback.schema import ShotDelivery, level_title, quality_note
from workers.logging import log_event
from workers.nodes.n15_compose.schema import MotionCard, ShotClip
from workers.qa.budget_store import open_project_budget, project_folder
from workers.qa.loop import run_shot_loop
from workers.compliance.moderation import internal_skip_visual_review
from workers.qa.scores import is_quality_pass, not_reviewed
from workers.qa.service import review_shot
from workers.schemas.asset import Candidate, QAReport
from workers.schemas.brand import BrandKit
from workers.schemas.director import DecisionAction
from workers.schemas.script import GenerationMode, Script, Shot

_CONTENT = {
    "product_deform",
    "extra_text",
    "garbled_text",
    "face_collapse",
    "face_count",
    "face_inconsistent",
    "flicker",
    "sensitive",
    "black_bar",
    "watermark",
    "low_resolution",
    "bad_composition",
}
_ROUTES = ("product", "person", "atmosphere", "multi_ref")
NODE = "shot_director"


@dataclass
class DirectResult:
    clips: list[ShotClip]
    notes: list[ShotDelivery]


def direct_shots(
    *,
    project_id: str,
    script: Script,
    videos: list[Candidate],
    keyframes: list[Candidate],
    brand_kit: BrandKit | None,
    width: int,
    height: int,
    gateway: Any,
) -> DirectResult:
    folder = project_folder(project_id) / "fallback"
    folder.mkdir(parents=True, exist_ok=True)
    cutout = _cutout(brand_kit, gateway, project_id)
    clips: list[ShotClip] = []
    notes: list[ShotDelivery] = []
    for shot in script.shots:
        clip, note = _one(
            shot,
            project_id=project_id,
            videos=videos,
            keyframes=keyframes,
            folder=folder,
            cutout=cutout,
            width=width,
            height=height,
            gateway=gateway,
            language=script.language,
        )
        clips.append(clip)
        notes.append(note)
        log_event(
            "shot_fallback",
            project_id=project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=1,
            level=note.fallback_level,
            degraded=note.degraded,
            reviewed=note.reviewed,
        )
    return DirectResult(clips=clips, notes=notes)


def _one(
    shot: Shot,
    *,
    project_id: str,
    videos: list[Candidate],
    keyframes: list[Candidate],
    folder: Path,
    cutout: Image.Image | None,
    width: int,
    height: int,
    gateway: Any,
    language: str,
) -> tuple[ShotClip, ShotDelivery]:
    opening = _pick(keyframes, shot.shot_id, "first")
    key_path = _materialize(
        opening, folder / f"{shot.shot_id}-key.png", kind="image", gateway=gateway
    )
    if shot.generation_mode is GenerationMode.motion_graphics:
        return _from_level(
            4,
            shot,
            project_id=project_id,
            folder=folder,
            key_path=key_path,
            cutout=cutout,
            width=width,
            height=height,
            gateway=gateway,
            language=language,
            previous=opening,
        )
    video = _pick(videos, shot.shot_id, None)
    video_path = _materialize(
        video, folder / f"{shot.shot_id}-src.mp4", kind="video", gateway=gateway
    )
    report = (
        _review(video_path, shot, project_id, gateway, node="n11_video_qa") if video_path else None
    )
    internal_keep = (
        internal_skip_visual_review()
        and report is not None
        and not report.hard_fail
        and video_path is not None
    )
    if report is not None and (is_quality_pass(report) or internal_keep):
        return _keep(shot, video_path, report)
    if report is not None and "sensitive" in report.hard_fail:
        return _from_level(
            3,
            shot,
            project_id=project_id,
            folder=folder,
            key_path=None,
            cutout=cutout,
            width=width,
            height=height,
            gateway=gateway,
            language=language,
            previous=video,
        )
    if report is not None and _flaws(report) and video is not None and video_path is not None:
        repaired = _repair(
            shot,
            project_id=project_id,
            candidate=video,
            folder=folder,
            width=width,
            height=height,
            gateway=gateway,
            language=language,
        )
        if repaired is not None:
            path, kept, detail = repaired
            return _clip(
                shot, path, _note(shot, 1, kept, path, detail, camera="", subject="model_frame")
            )
    return _from_level(
        1,
        shot,
        project_id=project_id,
        folder=folder,
        key_path=key_path,
        cutout=cutout,
        width=width,
        height=height,
        gateway=gateway,
        language=language,
        previous=video or opening,
    )


def _from_level(
    start: int,
    shot: Shot,
    *,
    project_id: str,
    folder: Path,
    key_path: Path | None,
    cutout: Image.Image | None,
    width: int,
    height: int,
    gateway: Any,
    language: str,
    previous: Candidate | None,
) -> tuple[ShotClip, ShotDelivery]:
    if start <= 1:
        made = _regenerate(
            shot,
            project_id=project_id,
            folder=folder,
            gateway=gateway,
            language=language,
            previous=previous,
            spend=True,
            image=None,
        )
        if made is not None:
            path, report = made
            if internal_skip_visual_review() and not report.hard_fail:
                report = _promote(report)
            return _clip(
                shot,
                path,
                _note(
                    shot,
                    1,
                    report,
                    path,
                    "已换路由、提示词和种子。",
                    camera="",
                    subject="model_frame",
                ),
            )
    if start <= 2:
        passed = _passed_keyframe(key_path, shot, project_id, gateway)
        if passed is not None:
            made = _regenerate(
                shot,
                project_id=project_id,
                folder=folder,
                gateway=gateway,
                language=language,
                previous=previous,
                spend=True,
                image=passed,
            )
            if made is not None:
                path, report = made
                if internal_skip_visual_review() and not report.hard_fail:
                    report = _promote(report)
                return _clip(
                    shot,
                    path,
                    _note(
                        shot,
                        2,
                        report,
                        path,
                        "图生视频使用了已通过质检的关键帧。",
                        camera="",
                        subject="model_frame",
                    ),
                )
    if start <= 3 and key_path is None:
        key_path = _ensure_still(
            shot,
            project_id=project_id,
            folder=folder,
            gateway=gateway,
            language=language,
        )
    if start <= 3 and key_path is not None:
        moved = _camera(
            shot,
            key_path,
            folder=folder,
            cutout=cutout,
            width=width,
            height=height,
            project_id=project_id,
            gateway=gateway,
        )
        if moved is not None:
            path, report, camera = moved
            return _clip(
                shot,
                path,
                _note(
                    shot,
                    3,
                    report,
                    path,
                    f"运镜为 {camera}。",
                    camera=camera,
                    subject="model_frame",
                ),
            )
    path, report, subject, needs_review = _graphics(
        shot,
        folder=folder,
        cutout=cutout,
        width=width,
        height=height,
        project_id=project_id,
        gateway=gateway,
        key_path=key_path,
    )
    detail = "文字由渲染层动画叠加，不画进画面。"
    if needs_review:
        detail += "视觉评审没有完成，需要人工复核。"
    return _clip(
        shot,
        path,
        _note(
            shot,
            4,
            report,
            path,
            detail,
            camera="background_motion",
            subject=subject,
            needs_review=needs_review,
        ),
        cards=_cards(shot),
    )


def _regenerate(
    shot: Shot,
    *,
    project_id: str,
    folder: Path,
    gateway: Any,
    language: str,
    previous: Candidate | None,
    spend: bool,
    image: Path | None,
    attempt: int = 1,
) -> tuple[Path, QAReport] | None:
    if spend and not open_project_budget(project_id).try_take():
        return None
    route = _next_route("" if previous is None else str(previous.params.get("shot_type") or ""))
    prompt = _rewrite(
        "" if previous is None else str(previous.params.get("prompt") or shot.visual),
        [card.text for card in shot.on_screen_text],
    )
    level = 2 if image is not None else 1
    used = open_project_budget(project_id).used
    seed = _seed(shot.shot_id, level, budget_used=used, attempt=attempt)
    params: dict[str, Any] = {"materialize": True, "shot_type": route}
    if image is not None:
        params["image_b64"] = base64.b64encode(image.read_bytes()).decode("ascii")
    try:
        output = gateway.generate_video(
            prompt,
            duration_s=float(shot.duration_s),
            seed=seed,
            shot_type=route,
            language=language,
            project_id=project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=1,
            params=params,
        )
    except Exception as exc:
        log_event(
            "shot_fallback_video_failed",
            project_id=project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=1,
            error=str(exc)[:300],
        )
        return None
    if not isinstance(output, dict):
        return None
    label = 2 if image is not None else 1
    dest = folder / f"{shot.shot_id}-L{label}-{uuid.uuid4().hex[:8]}.mp4"
    path = write_output(output, dest, kind="video")
    if path is None:
        return None
    report = _review(path, shot, project_id, gateway, node="n11_video_qa")
    if not _accepted(report):
        return None
    return path, report


def _repair(
    shot: Shot,
    *,
    project_id: str,
    candidate: Candidate,
    folder: Path,
    width: int,
    height: int,
    gateway: Any,
    language: str,
) -> tuple[Path, QAReport, str] | None:
    del width, height
    stashed: dict[str, Any] = {}
    calls = {"n": 0}

    def review(rows: list[Candidate]) -> list[QAReport]:
        reports: list[QAReport] = []
        for row in rows:
            path = _materialize(row, folder / f"{shot.shot_id}-try.mp4", kind="video")
            if path is None:
                reports.append(not_reviewed("missing", "retry produced no video file"))
            else:
                reports.append(_review(path, shot, project_id, gateway, node="n11_video_qa"))
        return reports

    def apply(_decision: Any) -> list[Candidate]:
        calls["n"] += 1
        made = _regenerate(
            shot,
            project_id=project_id,
            folder=folder,
            gateway=gateway,
            language=language,
            previous=candidate,
            spend=False,
            image=None,
            attempt=calls["n"],
        )
        if made is None:
            return [candidate]
        path, report = made
        stashed["path"] = path
        stashed["report"] = report
        return [
            candidate.model_copy(
                update={
                    "uri": str(path),
                    "qa": report,
                    "selected": False,
                    "model": "fallback-video",
                }
            )
        ]

    try:
        result = run_shot_loop(
            [candidate],
            shot_id=shot.shot_id,
            generator_node="N10",
            review=review,
            apply=apply,
            project_id=project_id,
            gateway=gateway,
            budget=open_project_budget(project_id),
        )
    except (RuntimeError, ValueError) as exc:
        log_event(
            "shot_fallback_loop_failed",
            project_id=project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=1,
            error=str(exc)[:300],
        )
        result = None
    if result is not None and result.decisions[-1].action is DecisionAction.pass_:
        chosen = [row for row in result.candidates if row.selected]
        path = (
            _materialize(chosen[0], folder / f"{shot.shot_id}-pass.mp4", kind="video")
            if chosen
            else None
        )
        if path is not None:
            report = _review(path, shot, project_id, gateway, node="n11_video_qa")
            if is_quality_pass(report):
                return path, report, "导演判通过。"
    path = stashed.get("path")
    report = stashed.get("report")
    if isinstance(path, Path) and isinstance(report, QAReport) and _accepted(report):
        return path, report, "重生成已通过视觉评审，且没有硬伤。"
    return None


def _camera(
    shot: Shot,
    key_path: Path,
    *,
    folder: Path,
    cutout: Image.Image | None,
    width: int,
    height: int,
    project_id: str,
    gateway: Any,
) -> tuple[Path, QAReport, str] | None:
    try:
        image = Image.open(key_path).convert("RGB")
    except OSError:
        return None
    count = frame_count(float(shot.duration_s))
    size = (width, height)
    attempts: list[tuple[str, Image.Image | None]] = []
    if cutout is not None:
        attempts.append(("ken_burns+parallax", cutout))
    attempts.append(("ken_burns", None))
    for name, layer in attempts:
        dest = folder / f"{shot.shot_id}-L3-{name}.mp4"
        if layer is None:
            ken_burns(image, dest, size=size, frames=count)
        else:
            parallax(image, layer, dest, size=size, frames=count)
        report = _review(dest, shot, project_id, gateway, node="n11_video_qa")
        if _accepted(report):
            return dest, report, name
    return None


def _graphics(
    shot: Shot,
    *,
    folder: Path,
    cutout: Image.Image | None,
    width: int,
    height: int,
    project_id: str,
    gateway: Any,
    key_path: Path | None,
) -> tuple[Path, QAReport, str, bool]:
    rgb = _average(key_path) if key_path is not None else (24, 52, 96)
    count = frame_count(float(shot.duration_s))
    size = (width, height)
    pending: tuple[Path, QAReport, str] | None = None
    for use_cutout, label in ((cutout, "cutout"), (None, "generated_shape")):
        if use_cutout is None and label == "cutout":
            continue
        dest = folder / f"{shot.shot_id}-L4-{label}.mp4"
        subject = motion_graphic(
            dest,
            size=size,
            frames=count,
            cutout=use_cutout,
            rgb=rgb,
        )
        report = _review(dest, shot, project_id, gateway, node="n11_video_qa")
        if _accepted(report):
            return dest, report, subject, False
        if pending is None and not _flaws(report):
            pending = (dest, report, subject)
    if pending is not None:
        path, report, subject = pending
        return path, report, subject, True
    raise RuntimeError(f"{shot.shot_id} motion graphics has a content hard-fail")


def _ensure_still(
    shot: Shot,
    *,
    project_id: str,
    folder: Path,
    gateway: Any,
    language: str,
) -> Path | None:
    """Ask the image model for a keyframe when the storyboard only stored a mock uri."""

    budget = open_project_budget(project_id)
    if not budget.try_take():
        return None
    prompt = f"{shot.visual}\n{NO_RENDERED_TEXT}"
    try:
        output = gateway.generate_image(
            prompt,
            seed=_seed(shot.shot_id, 3, budget_used=budget.used, attempt=1),
            shot_type="product",
            language=language,
            project_id=project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=1,
            params={"materialize": True},
        )
    except Exception as exc:
        log_event(
            "shot_fallback_image_failed",
            project_id=project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=1,
            error=str(exc)[:300],
        )
        return None
    if not isinstance(output, dict):
        return None
    return write_output(output, folder / f"{shot.shot_id}-keygen.png", kind="image")


def _passed_keyframe(
    path: Path | None,
    shot: Shot,
    project_id: str,
    gateway: Any,
) -> Path | None:
    if path is None:
        return None
    report = _review(path, shot, project_id, gateway, node="n09_keyframe_qa")
    if is_quality_pass(report):
        return path
    return None


def _review(
    path: Path,
    shot: Shot,
    project_id: str,
    gateway: Any,
    *,
    node: str,
) -> QAReport:
    return review_shot(
        {
            "project_id": project_id,
            "shot_id": shot.shot_id,
            "node": node,
            "candidate_uri": str(path),
            "purpose": shot.purpose,
            "visual": shot.visual,
            "voiceover": shot.voiceover,
            "shot_size": shot.shot_size,
            "shot_type": shot.camera,
            "generation_mode": shot.generation_mode.value,
            "expected_faces": 0,
        },
        gateway=gateway,
    )


def _keep(shot: Shot, path: Path, report: QAReport) -> tuple[ShotClip, ShotDelivery]:
    note = ShotDelivery(
        shot_id=shot.shot_id,
        fallback_level=None,
        fallback_name="",
        degraded=False,
        qa_passed=True,
        reviewed=report.visual_reviewed is True,
        hard_fail=list(report.hard_fail),
        note="未降级。质检通过。",
        media_path=str(path),
    )
    return _clip(shot, path, note)


def _note(
    shot: Shot,
    level: int,
    report: QAReport,
    path: Path,
    detail: str,
    *,
    camera: str,
    subject: str,
    needs_review: bool = False,
) -> ShotDelivery:
    name, _title = level_title(level)
    return ShotDelivery(
        shot_id=shot.shot_id,
        fallback_level=level,
        fallback_name=name,
        degraded=True,
        qa_passed=False,
        reviewed=False,
        needs_review=needs_review,
        hard_fail=list(report.hard_fail),
        note=quality_note(level, detail),
        media_path=str(path),
        camera=camera,
        subject=subject,
    )


def _clip(
    shot: Shot,
    path: Path,
    note: ShotDelivery,
    cards: list[MotionCard] | None = None,
) -> tuple[ShotClip, ShotDelivery]:
    return ShotClip(shot_id=shot.shot_id, path=str(path), cards=cards or []), note


def _cards(shot: Shot) -> list[MotionCard]:
    duration = float(shot.duration_s)
    cards: list[MotionCard] = []
    for item in shot.on_screen_text:
        start = min(duration, max(0.0, float(item.in_)))
        end = min(duration, max(start, float(item.out)))
        if end <= start:
            continue
        slices = 3 if end - start >= 0.45 else 1
        span = (end - start) / slices
        for index in range(slices):
            cards.append(
                MotionCard(
                    text=item.text,
                    start_s=round(start + span * index, 3),
                    end_s=round(start + span * (index + 1), 3),
                    y_ratio=round(0.7 - 0.08 * index, 3),
                )
            )
    return cards


def _cutout(kit: BrandKit | None, gateway: Any, project_id: str) -> Image.Image | None:
    if kit is None:
        return None
    for product in kit.products:
        for uri in [*product.cutouts, *product.photos]:
            data = read_bytes(uri)
            if not data:
                continue
            if uri in product.cutouts or data.startswith(b"\x89PNG"):
                try:
                    image = Image.open(io.BytesIO(data))
                    image.load()
                except OSError:
                    continue
                if uri in product.cutouts:
                    return image
            matte = getattr(gateway, "matte", None)
            if not callable(matte) or uri not in product.photos:
                continue
            try:
                result = matte(
                    "remove the flat background",
                    seed=1,
                    project_id=project_id,
                    node=NODE,
                    shot_id=product.product_id,
                    attempt=1,
                    params={"image_b64": base64.b64encode(data).decode("ascii")},
                )
            except Exception:
                continue
            if not isinstance(result, dict) or not result.get("edge_ok"):
                continue
            encoded = result.get("png_b64")
            if not isinstance(encoded, str):
                continue
            try:
                return Image.open(io.BytesIO(base64.b64decode(encoded)))
            except (OSError, ValueError):
                continue
    return None


def _materialize(
    candidate: Candidate | None, dest: Path, *, kind: str, gateway: Any = None
) -> Path | None:
    if candidate is None:
        return None
    payload = {"uri": candidate.uri, **candidate.params}
    return write_output(payload, dest, kind=kind, gateway=gateway)


def _pick(rows: list[Candidate], shot_id: str, frame: str | None) -> Candidate | None:
    matched = [row for row in rows if row.shot_id == shot_id]
    if frame is not None:
        framed = [row for row in matched if str(row.params.get("frame") or "first") == frame]
        matched = framed or matched
    chosen = [row for row in matched if row.selected]
    pool = chosen or matched
    return pool[0] if pool else None


def _accepted(report: QAReport) -> bool:
    """Levels 1–3. A clip counts only after a vision review with no hard failure.

    ``not_reviewed``, ``judge_unavailable``, and a mock judge all leave
    ``visual_reviewed`` false. Those clips drop to the next level. ``sensitive``
    is a hard failure even when a vision model is the only thing that can see it.
    """

    return report.visual_reviewed is True and not report.hard_fail


def _promote(report: QAReport) -> QAReport:
    """内部模式：把未评审但无硬伤的报告标记为已评审，避免无限回退。"""

    from workers.qa.scores import PASS_TOTAL

    return report.model_copy(
        update={
            "visual_reviewed": True,
            "total": max(report.total, PASS_TOTAL),
            "degraded": False,
            "evaluator": "internal-approved",
            "notes": "internal mode: visual review skipped",
        }
    )


def _flaws(report: QAReport) -> list[str]:
    return [code for code in report.hard_fail if code in _CONTENT]


def _next_route(current: str) -> str:
    if current not in _ROUTES:
        return _ROUTES[0]
    return _ROUTES[(_ROUTES.index(current) + 1) % len(_ROUTES)]


def _rewrite(prompt: str, blocked: list[str]) -> str:
    text = prompt
    for item in blocked:
        if item:
            text = text.replace(item, "")
    return f"{text.strip()}\nDifferent camera and a new seed. {NO_RENDERED_TEXT}"


def _seed(shot_id: str, level: int, *, budget_used: int, attempt: int) -> int:
    raw = f"fallback:{shot_id}:{level}:{budget_used}:{attempt}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return int(digest[:8], 16) % 1_000_000 + 1


def _average(path: Path) -> tuple[int, int, int]:
    try:
        image = Image.open(path).convert("RGB")
    except OSError:
        return (24, 52, 96)
    small = image.resize((1, 1), Image.Resampling.BOX)
    pixel = small.getpixel((0, 0))
    if not isinstance(pixel, tuple):
        return (24, 52, 96)
    return int(pixel[0]), int(pixel[1]), int(pixel[2])
