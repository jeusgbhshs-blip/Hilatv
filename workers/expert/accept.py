"""Measure T19 on the files a mock film actually wrote."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from workers.expert.canvas import build_canvas
from workers.expert.charge import BudgetExhausted, reserve
from workers.expert.rerun import select_candidate
from workers.expert.seed import build_film
from workers.media.trim import probe_duration_s
from workers.qa.budget_store import open_project_budget
from workers.qa.settings import project_retry_cap
from workers.workflow.store import init_project, project_path, read_snapshot


def main() -> None:
    os.environ["HILATV_LIVE"] = "0"
    project_id = os.environ.get("HILATV_EXPERT_PROJECT", "t19expert")
    build_film(project_id)
    print(f"project_id={project_id}")
    print(measure(project_id))


def measure(project_id: str) -> str:
    canvas = build_canvas(project_id)
    keyframes = [item for shot in canvas["shots"] for item in shot["keyframes"]]
    videos = [item for shot in canvas["shots"] for item in shot["videos"]]
    media = project_path(project_id) / "media"
    pngs = sorted(media.glob("*.png"))
    mp4s = sorted(media.glob("*.mp4"))
    if len(pngs) != len(keyframes):
        raise SystemExit(f"png files {len(pngs)} != keyframe records {len(keyframes)}")
    if len(mp4s) != len(videos):
        raise SystemExit(f"mp4 files {len(mp4s)} != video records {len(videos)}")
    durations = [probe_duration_s(path.read_bytes()) for path in mp4s]
    if any(item <= 0 for item in durations):
        raise SystemExit(f"mp4 duration not measured: {durations}")
    reviewed = sum(1 for item in keyframes + videos if item["verdict"]["visual_reviewed"] is True)
    passed = sum(1 for item in keyframes + videos if item["verdict"]["qa_passed"] is True)
    leaked = [
        item
        for item in keyframes + videos
        if item["verdict"]["qa_passed"] and item["verdict"]["visual_reviewed"] is not True
    ]
    if leaked:
        raise SystemExit("unreviewed candidate was marked qa_passed")
    changed = _master_changed(project_id, videos)
    if not changed:
        raise SystemExit("selecting another video did not change the master file")
    limit = project_retry_cap()
    probe_id = "t19budget"
    init_project(probe_id, sentence="预算探针", status="completed")
    budget = open_project_budget(probe_id)
    while budget.try_take():
        pass
    try:
        reserve(probe_id, "n08_keyframe")
    except BudgetExhausted as exc:
        refusal = str(exc)
    else:
        raise SystemExit("exhausted budget still accepted a generative re-run")
    rolled = _rollback_snapshot(probe_id)
    if rolled != limit:
        raise SystemExit(f"rollback lowered the ledger from {limit} to {rolled}")
    film_budget = open_project_budget(project_id)
    if film_budget.used != 0:
        raise SystemExit("building the film charged a re-run")
    return (
        f"accept-t19: keyframes={len(keyframes)} videos={len(videos)} "
        f"png_files={len(pngs)} mp4_files={len(mp4s)} "
        f"mp4_duration_s={round(sum(durations), 3)} "
        f"visual_reviewed={reviewed} qa_passed={passed} master_changed=1 "
        f"budget_used={open_project_budget(probe_id).used} budget_limit={limit} "
        f"refusal={refusal} 未测=视觉评审通过率"
    )


def _master_changed(project_id: str, videos: list[dict]) -> bool:
    snapshot = read_snapshot(project_id) or {}
    master = Path(str(snapshot.get("deliverable") or ""))
    if not master.is_file():
        raise SystemExit("master file is missing")
    before = hashlib.sha256(master.read_bytes()).hexdigest()
    other = next((item for item in videos if not item["selected"]), None)
    if other is None:
        raise SystemExit("no alternate video candidate")
    select_candidate(project_id, "n10_video", other["shot_id"], other["candidate_id"])
    again = read_snapshot(project_id) or {}
    updated = Path(str(again.get("deliverable") or ""))
    if not updated.is_file():
        raise SystemExit("master missing after select")
    after = hashlib.sha256(updated.read_bytes()).hexdigest()
    return before != after


def _rollback_snapshot(project_id: str) -> int:
    """Restore an older project.json. The regen ledger must stay where it is."""

    folder = project_path(project_id)
    snapshot = folder / "project.json"
    backup = snapshot.read_text(encoding="utf-8")
    failed = '{"project_id": "' + project_id + '", "status": "failed"}\n'
    snapshot.write_text(failed, encoding="utf-8")
    snapshot.write_text(backup, encoding="utf-8")
    nodes = folder / "nodes"
    if nodes.is_dir():
        for path in nodes.glob("*.json"):
            path.write_text("{}\n", encoding="utf-8")
            path.write_text("{}\n", encoding="utf-8")
    return open_project_budget(project_id).used


if __name__ == "__main__":
    main()
