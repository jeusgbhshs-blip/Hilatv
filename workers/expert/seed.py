"""Build a one-shot project with real keyframe and video files.

Used by the acceptance script and the canvas tests. The gateway is the mock
adapter. No live key is read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gateway.adapters.mock_adapter import MockAdapter
from workers.expert.gates import enforce_review
from workers.expert.invoke import invoke_node
from workers.nodes.media_gateway import build_media_gateway
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.nodes.runtime import read_bytes
from workers.qa.service import review_shot
from workers.schemas.asset import Candidate
from workers.workflow.store import (
    init_project,
    load_checkpoint,
    project_path,
    save_node,
    update_snapshot,
)


def build_film(project_id: str, *, gateway: Any | None = None) -> dict[str, Any]:
    """Run N8 through N15 for one shot and keep the media inside the project."""

    root = project_path(project_id, create=True)
    if gateway is None:
        gateway_dir = root / "gateway"
        gateway_dir.mkdir(parents=True, exist_ok=True)
        gateway = build_media_gateway(gateway_dir)
    voice_dir = root / "voice-gateway"
    voice_dir.mkdir(parents=True, exist_ok=True)
    voice_gateway = build_media_gateway(voice_dir)
    voice_gateway.registry["mock"] = MockAdapter(store=None)
    script = storyboard(
        shot(
            duration_s=1.0,
            voiceover="高压柱塞泵稳定运行。",
            on_screen_text=[{"text": "30 MPa", "style": "spec_badge", "in": 0.1, "out": 0.8}],
        )
    )
    init_project(
        project_id,
        sentence="给我们的柱塞泵做个1秒特写",
        status="completed",
        keyframe_candidates=3,
        video_candidates=3,
        shots=[{"shot_id": "S01", "order": 1, "purpose": script["shots"][0]["purpose"]}],
    )
    save_node(project_id, "n05_storyboard", {"script": script})
    snapshot = {
        "keyframe_candidates": 3,
        "video_candidates": 3,
        "sentence": "给我们的柱塞泵做个1秒特写",
    }
    state: dict[str, Any] = {"script": script, "completed": ["n05_storyboard"]}
    for name in (
        "n06_voiceover",
        "n08_keyframe",
        "n10_video",
        "n12_music",
        "n13_subtitle",
        "n14_packaging",
        "n15_compose",
    ):
        patch = invoke_node(
            name,
            project_id=project_id,
            state=state,
            snapshot=snapshot,
            gateway=voice_gateway if name == "n06_voiceover" else gateway,
        )
        if name == "n08_keyframe":
            patch["keyframes"] = _on_disk(
                gateway, patch["keyframes"], root / "media", ".png", project_id, "n09_keyframe"
            )
        elif name == "n10_video":
            patch["videos"] = _on_disk(
                gateway, patch["videos"], root / "media", ".mp4", project_id, "n11_video"
            )
        current = {}
        path = root / "nodes" / f"{name}.json"
        if path.is_file():
            import json

            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        current.update(patch)
        save_node(project_id, name, current)
        state.update(patch)
    update_snapshot(
        project_id,
        status="completed",
        phase="成片",
        deliverable=state.get("deliverable"),
        message="成片已就绪",
    )
    return {"project_id": project_id, "state": load_checkpoint(project_id), "gateway": gateway}


def _on_disk(
    gateway: Any,
    rows: list[dict[str, Any]],
    folder: Path,
    suffix: str,
    project_id: str,
    review_node: str,
) -> list[dict[str, Any]]:
    folder.mkdir(parents=True, exist_ok=True)
    stamped: list[dict[str, Any]] = []
    for raw in rows:
        candidate = Candidate.model_validate(raw)
        loaded = read_bytes(gateway, candidate.uri)
        if loaded is not None:
            dest = folder / f"{candidate.candidate_id}{suffix}"
            dest.write_bytes(loaded[1])
            candidate = candidate.model_copy(update={"uri": str(dest.resolve())})
        report = review_shot(
            {
                "project_id": project_id,
                "shot_id": candidate.shot_id,
                "node": review_node,
                "candidate_uri": candidate.uri,
                "model": candidate.model,
                "prompt": str(candidate.params.get("prompt") or ""),
            },
            gateway=gateway,
        )
        stamped.append(enforce_review(candidate, report).model_dump(mode="json"))
    return stamped
