"""Apply one sentence edit: rerun the affected nodes, keep the other shot files.

Partial reruns stay in this process. The Temporal film workflow only knows how
to start at a node and continue through every later shot, which would regenerate
work the change set said to keep.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from workers.logging import log_event
from workers.nodes.n18_revision.concept_gate import (
    classify_concept,
    delivery_passes,
    read_project_concept,
)
from workers.nodes.n18_revision.node import run as run_revision
from workers.nodes.n18_revision.qa import QAError
from workers.nodes.runtime import read_bytes
from workers.qa.budget_store import open_project_budget
from workers.qa.scores import is_quality_pass, not_reviewed
from workers.qa.service import review_shot
from workers.schemas.asset import QAReport
from workers.schemas.director import DecisionAction, DecisionTarget, DirectorDecision
from workers.schemas.script import Script, ShotStatus
from workers.workflow.contract import PIPELINE
from workers.workflow.store import locked_project, project_path, valid_project_id
from workers.workflow.versions import (
    _recover_restore,
    atomic_write,
    commit_locked,
    hashes,
    media_path,
)

_URL = re.compile(r"https?://[^\s]+")
_RENDER = ("n14", "n15", "n13", "n06", "n08", "n10")
END_CARD_NOTE = "片头和角标已去掉。片尾仍保留 Logo 和行动号召。"


class RevisionError(ValueError):
    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def revise_project(
    project_id: str,
    instruction: str,
    *,
    shot_id: str | None = None,
    gateway: Any | None = None,
) -> dict[str, Any]:
    if not valid_project_id(project_id):
        raise RevisionError("项目不存在", status=404)
    text = instruction.strip()
    if not text or len(text) > 4000:
        raise RevisionError("改稿内容无效")
    if shot_id is not None and (
        not isinstance(shot_id, str) or "/" in shot_id or "\\" in shot_id or ".." in shot_id
    ):
        raise RevisionError("镜头编号无效")
    with locked_project(project_id) as directory:
        _recover_restore(directory)
        snapshot = _read_snapshot(directory)
        if snapshot.get("status") == "running":
            raise RevisionError("项目仍在运行", status=409)
        if snapshot.get("status") != "completed":
            raise RevisionError("成片还没好", status=409)
        state = _state(directory)
        script = _script(state)
        if shot_id and shot_id not in {shot.shot_id for shot in script.shots}:
            raise RevisionError("镜头编号无效")
        held = {"snapshot": snapshot, "state": state}
    gateway = gateway if gateway is not None else _live_gateway()
    try:
        parsed = run_revision(
            {
                "project_id": project_id,
                "shot_id": shot_id,
                "payload": {
                    "instruction": text,
                    "script": script.model_dump(mode="json"),
                    "brand_kit": state.get("brand_kit"),
                    "focused_shot_id": shot_id,
                },
            },
            timeout_s=30,
            max_attempts=1,
            gateway=gateway,
        )
    except QAError as exc:
        raise RevisionError(str(exc)) from exc
    if parsed.payload.get("status") != "apply":
        return {
            "project_id": project_id,
            "version_id": None,
            "directive": None,
            "nodes": [],
            "video_shots": [],
            "quality_pass": False,
            "status": parsed.payload.get("status"),
            "question": parsed.payload.get("question") or "",
            "notice": parsed.payload.get("notice") or "",
            "concept_degraded": False,
            "concept_ok": None,
            "concept_text_source": "",
        }
    directory = project_path(project_id)
    _maybe_fetch_logo(directory, text, parsed.payload.get("directive") or {})
    outcome = _execute(
        directory,
        project_id,
        held["snapshot"],
        held["state"],
        parsed.payload,
        gateway=gateway,
    )
    with locked_project(project_id) as directory:
        _recover_restore(directory)
        snapshot = _read_snapshot(directory)
        state = held["state"]
        concept = read_project_concept(directory)
        view = classify_concept(concept)
        if not _index_items(directory):
            commit_locked(
                directory,
                snapshot,
                instruction="初版",
                quality_pass=False,
                concept_degraded=view.degraded,
                executed=[],
                video_shots=[],
                decisions=[],
                shot_reviews=_reviews_from_hashes(directory),
            )
            snapshot = _read_snapshot(directory)
        reviews = outcome["reviews"]
        passes = delivery_passes(reviews, concept if view.degraded or view.ok is False else concept)
        if view.degraded or view.ok is False:
            passes = False
        kept = list(outcome.get("kept_previous") or [])
        if kept:
            passes = False
        notice = str(parsed.payload.get("notice") or "")
        change = (parsed.payload.get("directive") or {}).get("change") or {}
        if change.get("logo") == "remove":
            notice = f"{notice} {END_CARD_NOTE}".strip()
        if kept:
            notice = f"{notice} 这些镜头没有新画面，已保留上一版：{'、'.join(kept)}。".strip()
        _store_media(directory, outcome.get("fresh") or {})
        deliverable = outcome.get("deliverable") or snapshot.get("deliverable")
        if outcome.get("master_path"):
            playback = directory / "playback" / "master.mp4"
            atomic_write(playback, Path(outcome["master_path"]).read_bytes())
            deliverable = str(playback.resolve())
        _write_patches(directory, outcome["patches"])
        manifest = commit_locked(
            directory,
            {**snapshot, "deliverable": deliverable},
            instruction=text,
            quality_pass=passes,
            concept_degraded=view.degraded or view.ok is False,
            executed=outcome["executed"],
            video_shots=outcome["video_shots"],
            decisions=outcome["decisions"],
            shot_reviews=reviews,
        )
        status = "incomplete" if kept else "completed"
        message = notice if kept or notice else "改稿已生成新版本"
        snapshot.update(
            {
                "status": "completed",
                "message": message,
                "current_version_id": manifest["version_id"],
                "quality_pass": passes,
                "deliverable": deliverable,
                "revision_notice": notice,
                "concept_degraded": view.degraded or view.ok is False,
                "concept_ok": False if view.degraded or view.ok is False else view.ok,
                "concept_text_source": view.text_source,
                "shots": [
                    {"shot_id": shot.shot_id, "order": shot.order, "purpose": shot.purpose}
                    for shot in Script.model_validate(outcome["script"]).shots
                ],
            }
        )
        snapshot.pop("regen_used", None)
        atomic_write(
            directory / "project.json",
            _json_bytes(snapshot),
        )
        log_event(
            "revision_committed",
            project_id=project_id,
            node="n18_revision",
            shot_id=shot_id,
            attempt=1,
            version_id=manifest["version_id"],
            quality_pass=passes,
        )
        return {
            "project_id": project_id,
            "version_id": manifest["version_id"],
            "directive": parsed.payload["directive"],
            "nodes": outcome["executed"],
            "video_shots": outcome["video_shots"],
            "quality_pass": passes,
            "concept_degraded": view.degraded or view.ok is False,
            "concept_ok": False if view.degraded or view.ok is False else view.ok,
            "concept_text_source": view.text_source,
            "status": status,
            "notice": notice,
            "kept_previous": kept,
            "question": "",
        }


def _execute(
    directory: Path,
    project_id: str,
    snapshot: dict[str, Any],
    state: dict[str, Any],
    payload: dict[str, Any],
    *,
    gateway: Any,
) -> dict[str, Any]:
    directive = payload["directive"]
    change = directive["change"]
    script = Script.model_validate(payload["script"])
    brand = payload.get("brand_kit")
    brief = state.get("brief")
    nodes: list[str] = list(payload.get("nodes") or [])
    planned_video: list[str] = list(payload.get("video_shots") or [])
    decisions: list[dict[str, Any]] = []
    video_shots: list[str] = []
    blocked: set[str] = set()
    budget = open_project_budget(project_id)
    for shot_id in planned_video:
        if not budget.try_take():
            blocked.add(shot_id)
            decisions.append(_blocked(shot_id, budget.limit))
            continue
        video_shots.append(shot_id)
    patches = _patches(directory)
    width, height = _canvas()
    executed: list[str] = []
    voiceovers = list(state.get("voiceovers") or [])
    keyframes = list(state.get("keyframes") or [])
    videos = list(state.get("videos") or [])
    cues = list(state.get("cues") or [])
    elements = list(state.get("elements") or [])
    intro_s = float(state.get("intro_s") or 0)
    outro_s = float(state.get("outro_s") or 0)
    fresh: dict[str, bytes] = {}
    kept: list[str] = []
    reviews = {shot.shot_id: _cached_review(shot.shot_id) for shot in script.shots}

    enterprise_id = _enterprise_id(snapshot)
    if "n06_voiceover" in nodes:
        script, voiceovers = _voice(
            project_id,
            script,
            voiceovers,
            directive["targets"],
            brand,
            brief if "n10_video" in nodes else None,
            gateway,
            keep_duration="n10_video" not in nodes,
            enterprise_id=enterprise_id,
        )
        executed.append("n06_voiceover")
    if "n08_keyframe" in nodes and video_shots:
        keyframes = _keyframes(
            project_id,
            script,
            keyframes,
            video_shots,
            brand,
            brief,
            gateway,
            enterprise_id=enterprise_id,
        )
        executed.append("n08_keyframe")
        executed.append("n09_keyframe_qa")
    if "n10_video" in nodes and video_shots:
        videos, made, skipped = _videos(
            directory,
            project_id,
            script,
            videos,
            keyframes,
            video_shots,
            brand,
            brief,
            gateway,
            enterprise_id=enterprise_id,
        )
        fresh.update(made)
        kept.extend(skipped)
        executed.extend(["n10_video", "n11_video_qa"])
        for shot_id, report in _review_new(directory, project_id, fresh, gateway).items():
            reviewed = report.visual_reviewed is True
            passed = bool(reviewed and is_quality_pass(report))
            reviews[shot_id] = {
                "shot_id": shot_id,
                "visual_reviewed": reviewed,
                "quality_pass": passed,
            }
            script = _mark_shot(script, shot_id, passed)
    if "n13_subtitle" in nodes and voiceovers:
        cues = _subtitles(directory, project_id, script, voiceovers, brand, brief, width, height)
        executed.append("n13_subtitle")
    ran_picture = bool(fresh) or "n06_voiceover" in executed or "n14_packaging" in nodes
    if "n14_packaging" in nodes:
        elements, intro_s, outro_s = _package(
            directory,
            project_id,
            script,
            brand,
            brief,
            width,
            height,
            brand_logo=change.get("logo") != "remove",
            enterprise_id=enterprise_id,
        )
        executed.append("n14_packaging")
        ran_picture = True
    deliverable = snapshot.get("deliverable")
    master_path = ""
    if ran_picture or ("n15_compose" in nodes and executed):
        master_path = _compose(
            directory,
            project_id,
            script,
            voiceovers,
            cues,
            elements,
            brand,
            brief,
            intro_s,
            outro_s,
            width,
            height,
        )
        executed.append("n15_compose")
        deliverable = master_path or deliverable
    _remember(
        patches,
        script=script,
        brand=brand,
        voiceovers=voiceovers,
        keyframes=keyframes,
        videos=videos,
        cues=cues,
        elements=elements,
        intro_s=intro_s,
        outro_s=outro_s,
        deliverable=deliverable,
    )
    ordered = [
        name
        for name in (
            "n06_voiceover",
            "n08_keyframe",
            "n09_keyframe_qa",
            "n10_video",
            "n11_video_qa",
            "n13_subtitle",
            "n14_packaging",
            "n15_compose",
        )
        if name in executed
    ]
    return {
        "executed": ordered,
        "video_shots": video_shots,
        "decisions": decisions,
        "reviews": [reviews[shot.shot_id] for shot in script.shots],
        "deliverable": deliverable,
        "master_path": master_path,
        "fresh": fresh,
        "kept_previous": kept,
        "script": script.model_dump(mode="json"),
        "patches": patches,
        "blocked": sorted(blocked),
    }


def _enterprise_id(snapshot: dict[str, Any]) -> str | None:
    """Enterprise on the stored project. Never a value from the edit request."""

    value = snapshot.get("enterprise_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _voice(
    project_id,
    script,
    voiceovers,
    targets,
    brand,
    brief,
    gateway,
    *,
    keep_duration: bool,
    enterprise_id: str | None = None,
):
    from workers.nodes.n06_voiceover.node import run

    wanted = set(targets)
    partial = wanted != {shot.shot_id for shot in script.shots}
    board = (
        script
        if not partial
        else script.model_copy(
            update={"shots": [shot for shot in script.shots if shot.shot_id in wanted]}
        )
    )
    result = run(
        {
            "project_id": project_id,
            "payload": {
                "script": board.model_dump(mode="json"),
                "brand_kit": brand,
                "brief": brief,
                "enterprise_id": enterprise_id,
            },
        },
        timeout_s=120,
        max_attempts=1,
        gateway=gateway,
    )
    updated = Script.model_validate(result.payload["script"])
    before = {shot.shot_id: shot for shot in script.shots}
    by_id = {shot.shot_id: shot for shot in updated.shots}
    merged_shots = []
    for shot in script.shots:
        new = by_id.get(shot.shot_id)
        if new is None:
            merged_shots.append(shot)
            continue
        if keep_duration:
            new = new.model_copy(
                update={
                    "duration_s": before[shot.shot_id].duration_s,
                    "on_screen_text": before[shot.shot_id].on_screen_text,
                }
            )
        merged_shots.append(new)
    takes = {item["shot_id"]: item for item in voiceovers if isinstance(item, dict)}
    for item in result.payload.get("voiceovers") or []:
        if isinstance(item, dict) and item.get("shot_id"):
            takes[item["shot_id"]] = item
    order = [shot.shot_id for shot in script.shots]
    return script.model_copy(update={"shots": merged_shots}), [
        takes[shot_id] for shot_id in order if shot_id in takes
    ]


def _keyframes(
    project_id,
    script,
    existing,
    shot_ids,
    brand,
    brief,
    gateway,
    *,
    enterprise_id: str | None = None,
):
    from workers.nodes.n08_keyframe.node import run

    merged = [
        row for row in existing if isinstance(row, dict) and row.get("shot_id") not in shot_ids
    ]
    for shot_id in shot_ids:
        result = run(
            {
                "project_id": project_id,
                "shot_id": shot_id,
                "payload": {
                    "script": script.model_dump(mode="json"),
                    "brief": brief,
                    "brand_kit": brand,
                    "keyframe_candidates": 3,
                    "enterprise_id": enterprise_id,
                },
            },
            timeout_s=120,
            max_attempts=1,
            gateway=gateway,
        )
        merged.extend(result.payload.get("candidates") or [])
    return merged


def _videos(
    directory,
    project_id,
    script,
    existing,
    keyframes,
    shot_ids,
    brand,
    brief,
    gateway,
    *,
    enterprise_id: str | None = None,
):
    from workers.nodes.n10_video.node import run

    merged = [
        row for row in existing if isinstance(row, dict) and row.get("shot_id") not in shot_ids
    ]
    made: dict[str, bytes] = {}
    skipped: list[str] = []
    for shot_id in shot_ids:
        try:
            result = run(
                {
                    "project_id": project_id,
                    "shot_id": shot_id,
                    "payload": {
                        "script": script.model_dump(mode="json"),
                        "candidates": keyframes,
                        "brief": brief,
                        "brand_kit": brand,
                        "video_candidates": 3,
                        "enterprise_id": enterprise_id,
                    },
                },
                timeout_s=180,
                max_attempts=1,
                gateway=gateway,
            )
        except Exception:
            skipped.append(shot_id)
            continue
        rows = result.payload.get("candidates") or []
        merged.extend(rows)
        selected = next((row for row in rows if row.get("selected")), rows[0] if rows else None)
        data = _candidate_bytes(gateway, selected)
        if not data:
            skipped.append(shot_id)
            continue
        scratch = directory / "render" / "review" / f"{shot_id}.bin"
        atomic_write(scratch, data)
        made[shot_id] = data
    return merged, made, skipped


def _review_new(directory, project_id, fresh, gateway) -> dict[str, QAReport]:
    reports: dict[str, QAReport] = {}
    for shot_id in fresh:
        path = directory / "render" / "review" / f"{shot_id}.bin"
        try:
            reports[shot_id] = review_shot(
                {
                    "project_id": project_id,
                    "shot_id": shot_id,
                    "node": "n11_video_qa",
                    "candidate_uri": str(path),
                },
                gateway=gateway,
            )
        except Exception as exc:
            reports[shot_id] = not_reviewed("broken", str(exc)[:200])
    return reports


def _subtitles(directory, project_id, script, voiceovers, brand, brief, width, height):
    from workers.nodes.n13_subtitle.node import run

    result = run(
        {
            "project_id": project_id,
            "payload": {
                "script": script.model_dump(mode="json"),
                "voiceovers": voiceovers,
                "brand_kit": brand,
                "brief": brief,
                "width": width,
                "height": height,
                "work_dir": str(_work(directory, "n13")),
            },
        },
        timeout_s=60,
        max_attempts=1,
    )
    return result.payload.get("cues") or []


def _package(
    directory,
    project_id,
    script,
    brand,
    brief,
    width,
    height,
    *,
    brand_logo: bool,
    enterprise_id: str | None = None,
):
    from workers.nodes.n14_packaging.node import run

    result = run(
        {
            "project_id": project_id,
            "payload": {
                "script": script.model_dump(mode="json"),
                "brand_kit": brand,
                "brief": brief,
                "width": width,
                "height": height,
                "work_dir": str(_work(directory, "n14")),
                "brand_logo": brand_logo,
                "enterprise_id": enterprise_id,
                "intro": None if brand_logo else "none",
            },
        },
        timeout_s=60,
        max_attempts=1,
    )
    return (
        result.payload.get("elements") or [],
        float(result.payload.get("intro_s") or 0),
        float(result.payload.get("outro_s") or 0),
    )


def _compose(
    directory,
    project_id,
    script,
    voiceovers,
    cues,
    elements,
    brand,
    brief,
    intro_s,
    outro_s,
    width,
    height,
):
    from workers.nodes.n15_compose.node import run

    result = run(
        {
            "project_id": project_id,
            "payload": {
                "script": script.model_dump(mode="json"),
                "voiceovers": voiceovers,
                "cues": cues,
                "elements": elements,
                "brand_kit": brand,
                "brief": brief,
                "intro_s": intro_s,
                "outro_s": outro_s,
                "width": width,
                "height": height,
                "work_dir": str(_work(directory, "n15")),
            },
        },
        timeout_s=180,
        max_attempts=1,
    )
    return str(Path(result.payload["exports"]["master"]).resolve())


def _maybe_fetch_logo(directory: Path, instruction: str, directive: dict[str, Any]) -> None:
    change = directive.get("change") or {}
    if change.get("logo") != "replace":
        return
    found = _URL.findall(instruction)
    if not found:
        return
    from workers.nodes.n01_brief.ssrf import UnsafeURL, fetch_bytes

    try:
        data, _mime = fetch_bytes(found[0], timeout=5, max_bytes=1_000_000)
    except UnsafeURL as exc:
        log_event(
            "revision_logo_fetch_blocked",
            project_id=directory.name,
            node="n18_revision",
            attempt=1,
            error=str(exc)[:200],
        )
        return
    except Exception as exc:
        log_event(
            "revision_logo_fetch_failed",
            project_id=directory.name,
            node="n18_revision",
            attempt=1,
            error=str(exc)[:200],
        )
        return
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return
    atomic_write(directory / "render" / "fetched-logo.png", data)


def _candidate_bytes(gateway: Any, row: dict[str, Any] | None) -> bytes | None:
    if not row:
        return None
    loaded = read_bytes(gateway, str(row.get("uri") or ""))
    if loaded is None:
        return None
    _store, data = loaded
    return data


def _mark_shot(script: Script, shot_id: str, passed: bool) -> Script:
    shots = []
    for shot in script.shots:
        if shot.shot_id != shot_id:
            shots.append(shot)
            continue
        status = ShotStatus.passed if passed else ShotStatus.pending
        shots.append(shot.model_copy(update={"status": status}))
    return script.model_copy(update={"shots": shots})


def _blocked(shot_id: str, limit: int) -> dict[str, Any]:
    decision = DirectorDecision(
        action=DecisionAction.fallback,
        target=DecisionTarget(node="N10", shot_id=shot_id),
        reason="项目重生次数已到上限",
        changes={"plan": "degrade", "project_retry_cap": limit},
        max_attempts_left=0,
    )
    return decision.model_dump(mode="json")


def _cached_review(shot_id: str) -> dict[str, Any]:
    return {"shot_id": shot_id, "visual_reviewed": False, "quality_pass": False}


def _store_media(directory: Path, fresh: dict[str, bytes]) -> None:
    for shot_id, data in fresh.items():
        path = media_path(directory, shot_id)
        if path.is_file() and path.read_bytes() == data:
            continue
        atomic_write(path, data)


def _remember(patches, **fields: Any) -> None:
    script = fields["script"]
    dumped = script.model_dump(mode="json")
    for patch in patches.values():
        if "script" in patch:
            patch["script"] = dumped
        if fields["brand"] is not None and "brand_kit" in patch:
            patch["brand_kit"] = fields["brand"]
    patches.setdefault("n05_storyboard", {})["script"] = dumped
    patches.setdefault("n06_voiceover", {}).update(
        {"script": dumped, "voiceovers": fields["voiceovers"], "brand_kit": fields["brand"]}
    )
    if fields["keyframes"]:
        patches.setdefault("n08_keyframe", {})["keyframes"] = fields["keyframes"]
    if fields["videos"]:
        patches.setdefault("n10_video", {}).update({"videos": fields["videos"], "script": dumped})
    if fields["cues"]:
        patches.setdefault("n13_subtitle", {})["cues"] = fields["cues"]
    if fields["elements"]:
        patches.setdefault("n14_packaging", {}).update(
            {
                "elements": fields["elements"],
                "intro_s": fields["intro_s"],
                "outro_s": fields["outro_s"],
                "brand_kit": fields["brand"],
            }
        )
    if fields["deliverable"]:
        patches.setdefault("n15_compose", {}).update(
            {
                "deliverable": fields["deliverable"],
                "script": dumped,
                "exports": {"master": fields["deliverable"]},
            }
        )


def _write_patches(directory: Path, patches: dict[str, dict[str, Any]]) -> None:
    folder = directory / "nodes"
    folder.mkdir(exist_ok=True)
    for node, patch in patches.items():
        if node not in PIPELINE:
            continue
        atomic_write(folder / f"{node}.json", _json_bytes(patch))


def _patches(directory: Path) -> dict[str, dict[str, Any]]:
    folder = directory / "nodes"
    found: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return found
    for node in PIPELINE:
        path = folder / f"{node}.json"
        if path.is_file():
            import json

            found[node] = json.loads(path.read_text(encoding="utf-8"))
    return found


def _state(directory: Path) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for patch in _patches(directory).values():
        state.update(patch)
    return state


def _script(state: dict[str, Any]) -> Script:
    raw = state.get("script")
    if not isinstance(raw, dict):
        raise RevisionError("还没有分镜，不能改稿", status=409)
    return Script.model_validate(raw)


def _read_snapshot(directory: Path) -> dict[str, Any]:
    import json

    path = directory / "project.json"
    if not path.is_file():
        raise RevisionError("项目不存在", status=404)
    return json.loads(path.read_text(encoding="utf-8"))


def _index_items(directory: Path) -> list[Any]:
    import json

    path = directory / "versions" / "index.json"
    if not path.is_file():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8"))
    items = loaded.get("items") if isinstance(loaded, dict) else None
    return list(items or [])


def _reviews_from_hashes(directory: Path) -> list[dict[str, Any]]:
    return [
        {"shot_id": shot_id, "visual_reviewed": False, "quality_pass": False}
        for shot_id in hashes(directory)
    ]


def revision_gateway(directory: Path) -> Any:
    """Mock gateway with call logs. No object store, so speech stays on mock://."""

    from decimal import Decimal

    from gateway.adapters.mock_adapter import MockAdapter
    from gateway.cache import MemoryCache
    from gateway.pricing import Pricing
    from gateway.router import RouteTable, default_routes_path
    from gateway.service import Gateway
    from gateway.store import SqlStore

    folder = directory / "gateway"
    folder.mkdir(parents=True, exist_ok=True)
    progress = folder / "progress.md"
    if not progress.exists():
        progress.write_text(
            "## 告警（预算超限等，由网关自动追加）\n\n<!-- hilatv:alerts -->\n\n## 每日日志\n",
            encoding="utf-8",
        )
    return Gateway(
        routes=RouteTable(default_routes_path()),
        store=SqlStore.sqlite(folder / "gateway.sqlite"),
        cache=MemoryCache(),
        pricing=Pricing.load(),
        registry={"mock": MockAdapter()},
        limits_fn=lambda: (False, Decimal("0"), Decimal("0")),
        progress_path=progress,
        model_overrides_fn=lambda: {},
    )


def _live_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()


def _work(directory: Path, name: str) -> Path:
    if name not in _RENDER:
        raise RevisionError("渲染目录无效")
    path = (directory / "render" / name).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise RevisionError("路径超出项目目录")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _canvas() -> tuple[int, int]:
    try:
        width = int(os.getenv("HILATV_RENDER_WIDTH") or "192")
        height = int(os.getenv("HILATV_RENDER_HEIGHT") or "108")
    except ValueError:
        return 192, 108
    return max(16, width), max(16, height)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
