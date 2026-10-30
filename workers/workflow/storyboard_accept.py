"""T23 acceptance: skip runs to a film; a narration edit touches one shot's file."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import time
from pathlib import Path

import httpx

from gateway import get_gateway
from workers.media.packaging import ai_label_text
from workers.workflow.runtime import shutdown_runtime
from workers.workflow.store import project_path

SENTENCE = "给我们的柱塞泵做个15秒宣传片，面向采购，风格稳重"
MARKER = "分镜旁白标记甲乙丙丁"


def main() -> int:
    asyncio.run(_run())
    return 0


async def _run() -> None:
    from app.main import app
    from workers.identity.session import open_session

    identity = open_session()
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {identity.token}"}
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=headers,
        ) as client:
            await _skip(client)
            await _preview(client)
        print("accept-t23 ok")
    finally:
        await shutdown_runtime()


async def _skip(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/v1/projects",
        json={"sentence": SENTENCE, "skip_storyboard": True},
    )
    assert created.status_code == 202, created.text
    project_id = created.json()["project_id"]
    body = await _wait(client, project_id, {"completed", "failed", "needs_human_review"})
    body = await _release_if_held(client, project_id, body)
    if body.get("status") != "completed":
        raise SystemExit(f"skip run did not finish: {body.get('status')} {body.get('error')}")
    if body.get("storyboard_gate") != "skip":
        raise SystemExit(f"skip run gate was {body.get('storyboard_gate')}")
    paused = [item for item in body.get("events") or [] if item.get("status") == "paused"]
    if paused:
        raise SystemExit("直接出片 paused")
    _playable(Path(str(_snapshot_path(project_id, "deliverable", body))))
    print(f"skip project={project_id} paused_events=0")


async def _preview(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/v1/projects",
        json={"sentence": SENTENCE, "skip_storyboard": False},
    )
    assert created.status_code == 202, created.text
    project_id = created.json()["project_id"]
    paused = await _wait(client, project_id, {"paused", "failed", "completed"})
    if paused.get("status") != "paused":
        raise SystemExit(f"preview did not pause: {paused.get('status')} {paused.get('message')}")
    cards = paused.get("storyboard") or []
    if len(cards) < 2:
        raise SystemExit(f"expected cards, got {len(cards)}")
    for card in cards:
        if card.get("visual_reviewed") is not False or card.get("preview_status") != "unavailable":
            raise SystemExit(f"mock frame was presented as a preview: {card}")
        if card.get("frame_url"):
            raise SystemExit("unavailable card has a frame url")
    directory = project_path(project_id)
    before = _hashes(directory)
    if len(before) < 2:
        raise SystemExit(f"voice files missing: {before}")
    shot_id = str(cards[0]["shot_id"])
    spoken = str(cards[0]["voiceover"]) + MARKER
    gateway = get_gateway()
    seq = len(gateway.store.list_logs(project_id=project_id))
    budget_before = _budget_used(directory)
    edited = await client.post(
        f"/v1/projects/{project_id}/storyboard/{shot_id}",
        json={"voiceover": spoken},
    )
    if edited.status_code != 200:
        raise SystemExit(f"edit failed {edited.status_code} {edited.text}")
    payload = edited.json()
    after = _hashes(directory)
    if after.get(shot_id) == before.get(shot_id):
        raise SystemExit("edited shot voice file did not change")
    unchanged = [key for key in before if key != shot_id]
    moved = [key for key in unchanged if after.get(key) != before[key]]
    if moved:
        raise SystemExit(f"other shot files changed: {moved}")
    if payload.get("prompt_contains_voiceover") is not False:
        raise SystemExit("edit reported a prompt leak")
    if payload.get("keyframe_pixels") != "未测":
        raise SystemExit(f"mock pixels were reported as measured: {payload.get('keyframe_pixels')}")
    prompts = (directory / "nodes" / "n08_keyframe.json").read_text(encoding="utf-8")
    if MARKER in prompts:
        raise SystemExit("narration marker entered a keyframe prompt")
    fresh = gateway.store.list_logs(project_id=project_id)[seq:]
    fresh_shots = {row.get("shot_id") for row in fresh if row.get("task") != "content_safety"}
    if not fresh or fresh_shots != {shot_id}:
        raise SystemExit(f"downstream calls were not limited to {shot_id}: {fresh}")
    safety = [row for row in fresh if row.get("task") == "content_safety"]
    if not safety or {row.get("shot_id") for row in safety} != {shot_id}:
        raise SystemExit("narration was not sent through content safety")
    if _budget_used(directory) != budget_before + 2:
        raise SystemExit("regen budget did not charge the voice and the frames")
    snapshot = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    if "regen_used" in snapshot:
        raise SystemExit("regen count was stored on the snapshot")
    continued = await client.post(f"/v1/projects/{project_id}/storyboard/continue")
    if continued.status_code != 200:
        raise SystemExit(f"continue failed {continued.status_code} {continued.text}")
    done = await _wait(client, project_id, {"completed", "failed", "needs_human_review"})
    done = await _release_if_held(client, project_id, done)
    if done.get("status") != "completed":
        raise SystemExit(f"preview run did not finish: {done.get('status')} {done.get('error')}")
    _assert_prompts(directory)
    _assert_label(directory)
    _playable(Path(str(done["deliverable"])))
    print(
        f"preview project={project_id} shot={shot_id} "
        f"changed={shot_id} unchanged={','.join(unchanged)} "
        f"keyframe_pixels=未测 visual_reviewed=false ai_label={ai_label_text()}"
    )


def _assert_prompts(directory: Path) -> None:
    for name in ("n08_keyframe.json", "n10_video.json"):
        text = (directory / "nodes" / name).read_text(encoding="utf-8")
        if MARKER in text:
            raise SystemExit(f"{name} contains the narration marker")


def _assert_label(directory: Path) -> None:
    raw = json.loads((directory / "nodes" / "n14_packaging.json").read_text(encoding="utf-8"))
    labels = [
        item
        for item in raw.get("elements") or []
        if isinstance(item, dict) and item.get("kind") == "ai_label"
    ]
    if len(labels) != 1 or labels[0].get("text") != ai_label_text():
        raise SystemExit(f"AI生成 label missing after the edit: {labels}")


def _hashes(directory: Path) -> dict[str, str]:
    folder = directory / "storyboard"
    found: dict[str, str] = {}
    if not folder.is_dir():
        return found
    for shot_dir in sorted(path for path in folder.iterdir() if path.is_dir()):
        wav = shot_dir / "voice.wav"
        if wav.is_file():
            found[shot_dir.name] = hashlib.sha256(wav.read_bytes()).hexdigest()
    return found


def _budget_used(directory: Path) -> int:
    path = directory / "regen_budget.json"
    if not path.is_file():
        return 0
    return int(json.loads(path.read_text(encoding="utf-8")).get("used") or 0)


def _snapshot_path(project_id: str, key: str, body: dict) -> str:
    value = body.get(key) or body.get("deliverable")
    if not isinstance(value, str) or not value:
        raise SystemExit(f"{project_id} has no {key}")
    return value


async def _release_if_held(client: httpx.AsyncClient, project_id: str, body: dict) -> dict:
    """Mock review leaves needs_review. Measure the film only after an explicit release."""

    if body.get("status") != "needs_human_review":
        return body
    if body.get("deliverable"):
        raise SystemExit(f"{project_id} already had a deliverable while held")
    released = await client.post(f"/v1/projects/{project_id}/human-review/release")
    if released.status_code != 202:
        raise SystemExit(f"release failed {released.status_code} {released.text}")
    return await _wait(client, project_id, {"completed", "failed"})


async def _wait(client: httpx.AsyncClient, project_id: str, terminal: set[str]) -> dict:
    deadline = time.monotonic() + 600
    last: dict = {}
    while time.monotonic() < deadline:
        response = await client.get(f"/v1/projects/{project_id}")
        if response.status_code != 200:
            raise SystemExit(f"status {response.status_code}")
        last = response.json()
        if last.get("status") in terminal:
            return last
        await asyncio.sleep(0.4)
    raise SystemExit(f"timed out: {last.get('status')} {last.get('node')} {last.get('message')}")


def _playable(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 32:
        raise SystemExit(f"master missing: {path}")
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        raise SystemExit(probe.stderr)
    duration = float((json.loads(probe.stdout or "{}").get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise SystemExit("master duration is 0")


if __name__ == "__main__":
    raise SystemExit(main())
