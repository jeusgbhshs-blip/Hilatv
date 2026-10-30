"""Storyboard cards shown after keyframe review and before video.

Narration edits reuse T16's per-shot voice and keyframe rerun. Image and video
prompts never receive the card text. Mock and flat placeholder frames are not
previews and are not reviewed. Regen spend goes through ``open_project_budget``
and is not copied into the project snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from workers.logging import log_event
from workers.nodes.n06_voiceover.node import load_take
from workers.qa.budget_store import open_project_budget
from workers.qa.service import review_shot
from workers.schemas.label_lock import LabelLocked, refuse_label_removal
from workers.schemas.script import Script
from workers.workflow.revise import _keyframes, _voice
from workers.workflow.store import locked_project, project_path, publish, valid_project_id
from workers.workflow.versions import atomic_write

GATE_NODE = "n09_keyframe_qa"
_SHOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,40}$")


class StoryboardError(ValueError):
    def __init__(self, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def prepare_gate(
    project_id: str,
    state: dict[str, Any],
    *,
    skip: bool,
    gateway: Any,
) -> dict[str, Any]:
    """Write one voice file per shot and the cards. Does not spend regen budget."""

    script = _script(state)
    voiceovers = _voice_list(state.get("voiceovers"))
    keyframes = _frame_list(state.get("keyframes"))
    reviews = _review_selected(project_id, script, keyframes, gateway)
    with locked_project(project_id) as directory:
        _write_voices(directory, script, voiceovers)
        cards = _cards(directory, script, keyframes, reviews)
        _write_index(directory, cards)
        snapshot = _read_snapshot(directory, project_id)
        snapshot["storyboard"] = [_public(card, project_id) for card in cards]
        snapshot["storyboard_gate"] = "skip" if skip else "hold"
        snapshot.pop("regen_used", None)
        if not skip:
            snapshot["status"] = "paused"
            snapshot["phase"] = "看分镜"
            snapshot["node"] = GATE_NODE
            snapshot["message"] = "分镜可以改旁白，确认后继续出片"
        _write_snapshot(directory, snapshot)
    if not skip:
        publish(
            project_id,
            {
                "node": GATE_NODE,
                "phase": "看分镜",
                "message": "分镜可以改旁白，确认后继续出片",
                "status": "paused",
            },
        )
    log_event(
        "storyboard_gate",
        project_id=project_id,
        node=GATE_NODE,
        attempt=1,
        skip=skip,
        shots=len(script.shots),
    )
    return {
        "storyboard_gate": "skip" if skip else "hold",
        "shot_reviews": [
            {
                "shot_id": card["shot_id"],
                "visual_reviewed": card["visual_reviewed"] is True,
                "preview_status": card["preview_status"],
            }
            for card in cards
        ],
    }


def sync_patch(project_id: str) -> dict[str, Any]:
    """Pull narration edits back into the workflow before video starts."""

    if not valid_project_id(project_id):
        return {}
    directory = project_path(project_id)
    voice = _read_node(directory, "n06_voiceover")
    frames = _read_node(directory, "n08_keyframe")
    patch: dict[str, Any] = {}
    if isinstance(voice.get("script"), dict):
        patch["script"] = voice["script"]
    if isinstance(voice.get("voiceovers"), list):
        patch["voiceovers"] = voice["voiceovers"]
    if isinstance(frames.get("keyframes"), list):
        patch["keyframes"] = frames["keyframes"]
    return patch


def edit_voiceover(
    project_id: str,
    shot_id: str,
    text: str,
    *,
    gateway: Any,
) -> dict[str, Any]:
    """Write one shot's narration back to the script and rerun only that shot."""

    spoken = text.strip()
    if not spoken or len(spoken) > 400 or "\x00" in spoken:
        raise StoryboardError("旁白无效")
    try:
        refuse_label_removal(spoken)
    except LabelLocked as exc:
        raise StoryboardError(str(exc)) from exc
    if not _SHOT.fullmatch(shot_id):
        raise StoryboardError("镜头编号无效")
    if not valid_project_id(project_id):
        raise StoryboardError("项目不存在", status=404)
    with locked_project(project_id) as directory:
        snapshot = _read_snapshot(directory, project_id)
        if snapshot.get("project_id") != project_id and not (directory / "project.json").is_file():
            raise StoryboardError("项目不存在", status=404)
        if not (directory / "project.json").is_file():
            raise StoryboardError("项目不存在", status=404)
        if snapshot.get("status") != "paused" or snapshot.get("storyboard_gate") != "hold":
            raise StoryboardError("现在不能改分镜", status=409)
        state = _film_state(directory)
        script = _script(state)
        if shot_id not in {shot.shot_id for shot in script.shots}:
            raise StoryboardError("镜头编号无效")
        before = _hash_voices(directory)
        voiceovers = _voice_list(state.get("voiceovers"))
        keyframes = _frame_list(state.get("keyframes"))
        brand = state.get("brand_kit") if isinstance(state.get("brand_kit"), dict) else None
        brief = state.get("brief") if isinstance(state.get("brief"), dict) else None
        current = next(shot.voiceover for shot in script.shots if shot.shot_id == shot_id)
    if spoken == current.strip():
        return _edit_body(
            project_id,
            shot_id,
            nodes=[],
            before=before,
            after=before,
            changed=False,
            blocked=False,
            voiceover=spoken,
        )
    updated = script.model_copy(
        update={
            "shots": [
                shot.model_copy(update={"voiceover": spoken}) if shot.shot_id == shot_id else shot
                for shot in script.shots
            ]
        }
    )
    # Brief is omitted so one shot is not stretched to the whole film length.
    updated, voiceovers = _voice(
        project_id,
        updated,
        voiceovers,
        [shot_id],
        brand,
        None,
        gateway,
        keep_duration=False,
    )
    nodes = ["n06_voiceover"]
    blocked = False
    budget = open_project_budget(project_id)
    if budget.try_take():
        keyframes = _keyframes(project_id, updated, keyframes, [shot_id], brand, brief, gateway)
        nodes.extend(["n08_keyframe", "n09_keyframe_qa"])
    else:
        blocked = True
    if _shot_prompts_contain(keyframes, shot_id, spoken):
        raise StoryboardError("旁白写进了画面提示词")
    reviews = _review_selected(project_id, updated, keyframes, gateway)
    with locked_project(project_id) as directory:
        _write_one_voice(directory, updated, voiceovers, shot_id)
        _write_voice_node(directory, updated, voiceovers)
        _write_frame_node(directory, keyframes)
        cards = _cards(directory, updated, keyframes, reviews)
        _write_index(directory, cards)
        snapshot = _read_snapshot(directory, project_id)
        snapshot["storyboard"] = [_public(card, project_id) for card in cards]
        snapshot["status"] = "paused"
        snapshot["phase"] = "看分镜"
        snapshot["node"] = GATE_NODE
        snapshot["storyboard_gate"] = "hold"
        snapshot.pop("regen_used", None)
        _write_snapshot(directory, snapshot)
        after = _hash_voices(directory)
    others = [key for key in before if key != shot_id]
    if any(before[key] != after.get(key) for key in others):
        raise StoryboardError("其他镜头的文件被改动了")
    log_event(
        "storyboard_edit",
        project_id=project_id,
        node=GATE_NODE,
        shot_id=shot_id,
        attempt=1,
        nodes=",".join(nodes),
        blocked=blocked,
    )
    return _edit_body(
        project_id,
        shot_id,
        nodes=nodes,
        before=before,
        after=after,
        changed=True,
        blocked=blocked,
        voiceover=spoken,
    )


def frame_file(project_id: str, shot_id: str) -> Path | None:
    """Real preview file, or nothing. Placeholders are never served."""

    if not valid_project_id(project_id) or not _SHOT.fullmatch(shot_id):
        return None
    directory = project_path(project_id).resolve()
    card = _index_card(directory, shot_id)
    if card is None or card.get("preview_status") != "ready":
        return None
    rel = card.get("frame_rel")
    if not isinstance(rel, str) or not rel or ".." in rel.split("/"):
        return None
    path = (directory / rel).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        return None
    if _is_placeholder(path):
        return None
    return path


def voice_hashes(project_id: str) -> dict[str, str]:
    if not valid_project_id(project_id):
        return {}
    return _hash_voices(project_path(project_id))


def public_cards(raw: Any, project_id: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cards: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        cards.append(_public(item, project_id))
    return cards


def _edit_body(
    project_id: str,
    shot_id: str,
    *,
    nodes: list[str],
    before: dict[str, str],
    after: dict[str, str],
    changed: bool,
    blocked: bool,
    voiceover: str,
) -> dict[str, Any]:
    directory = project_path(project_id)
    card = _index_card(directory, shot_id) or {}
    ready = card.get("preview_status") == "ready"
    reviewed = ready and card.get("visual_reviewed") is True
    return {
        "project_id": project_id,
        "shot_id": shot_id,
        "voiceover": voiceover,
        "nodes": nodes,
        "changed": changed,
        "budget_blocked": blocked,
        "hashes_before": before,
        "hashes_after": after,
        "visual_reviewed": reviewed,
        "preview_status": "ready" if ready else "unavailable",
        "keyframe_pixels": "未测" if not ready else "已记录",
        "prompt_contains_voiceover": False,
        "storyboard": public_cards(_read_index(directory).get("cards"), project_id),
    }


def _review_selected(
    project_id: str,
    script: Script,
    keyframes: list[dict[str, Any]],
    gateway: Any,
) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for shot in script.shots:
        row = _selected_opening(keyframes, shot.shot_id)
        uri = str(row.get("uri") or "") if row else ""
        try:
            report = review_shot(
                {
                    "project_id": project_id,
                    "shot_id": shot.shot_id,
                    "node": "n09_keyframe",
                    "candidate_uri": uri,
                    "model": str((row or {}).get("model") or ""),
                    "purpose": shot.purpose,
                    "visual": shot.visual,
                    # Card text stays out of the judge payload as well as image prompts.
                    "voiceover": "",
                    "shot_size": shot.shot_size,
                    "shot_type": shot.camera,
                    "generation_mode": shot.generation_mode.value,
                    "prompt": str(((row or {}).get("params") or {}).get("prompt") or ""),
                },
                gateway=gateway,
            )
        except Exception as exc:
            log_event(
                "storyboard_review_error",
                project_id=project_id,
                node=GATE_NODE,
                shot_id=shot.shot_id,
                attempt=1,
                error=str(exc)[:300],
            )
            found[shot.shot_id] = None
            continue
        found[shot.shot_id] = report
    return found


def _cards(
    directory: Path,
    script: Script,
    keyframes: list[dict[str, Any]],
    reviews: dict[str, Any],
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for shot in script.shots:
        row = _selected_opening(keyframes, shot.shot_id)
        uri = str(row.get("uri") or "") if row else ""
        kind, source = _classify(uri, directory)
        rel = ""
        if kind == "ready" and source is not None:
            rel = f"storyboard/{shot.shot_id}/frame{source.suffix.lower() or '.png'}"
            target = _inside(directory, directory / rel)
            if source.resolve() != target:
                atomic_write(target, source.read_bytes())
        else:
            _remove_frames(directory, shot.shot_id)
        report = reviews.get(shot.shot_id)
        flag = bool(report is not None and getattr(report, "visual_reviewed", None) is True)
        reviewed = kind == "ready" and flag
        cards.append(
            {
                "shot_id": shot.shot_id,
                "order": shot.order,
                "duration_s": shot.duration_s,
                "purpose": shot.purpose,
                "voiceover": shot.voiceover,
                "preview_status": "ready" if kind == "ready" else "unavailable",
                "visual_reviewed": reviewed,
                "preview_note": "" if reviewed else ("未评审" if kind == "ready" else "未测"),
                "frame_rel": rel if kind == "ready" else "",
            }
        )
    return cards


def _classify(uri: str, directory: Path) -> tuple[str, Path | None]:
    text = uri.strip()
    if not text or text.startswith("mock://") or text.startswith(("http://", "https://")):
        return "unavailable", None
    raw = text[7:] if text.startswith("file://") else text
    try:
        path = Path(raw).expanduser().resolve()
    except OSError:
        return "unavailable", None
    root = directory.resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return "unavailable", None
    if _is_placeholder(path):
        return "unavailable", None
    return "ready", path


def _is_placeholder(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.load()
            colors = image.convert("RGB").getcolors(maxcolors=2)
    except (UnidentifiedImageError, OSError, ValueError):
        return True
    return colors is not None and len(colors) == 1


def _public(card: dict[str, Any], project_id: str) -> dict[str, Any]:
    ready = card.get("preview_status") == "ready" and bool(card.get("frame_rel"))
    reviewed = ready and card.get("visual_reviewed") is True
    shot_id = str(card.get("shot_id") or "")
    return {
        "shot_id": shot_id,
        "order": card.get("order"),
        "duration_s": card.get("duration_s"),
        "purpose": str(card.get("purpose") or ""),
        "voiceover": str(card.get("voiceover") or ""),
        "preview_status": "ready" if ready else "unavailable",
        "visual_reviewed": reviewed,
        "preview_note": "" if reviewed else ("未评审" if ready else "未测"),
        "frame_url": (
            f"/v1/projects/{project_id}/storyboard/{shot_id}/frame" if ready and shot_id else None
        ),
    }


def _write_voices(directory: Path, script: Script, voiceovers: list[dict[str, Any]]) -> None:
    takes = {str(item.get("shot_id")): item for item in voiceovers}
    for shot in script.shots:
        take = takes.get(shot.shot_id)
        if take is None or not shot.voiceover.strip():
            continue
        _write_wav(directory, shot.shot_id, _wav_bytes(shot.voiceover, take, script.language))


def _write_one_voice(
    directory: Path,
    script: Script,
    voiceovers: list[dict[str, Any]],
    shot_id: str,
) -> None:
    shot = next(item for item in script.shots if item.shot_id == shot_id)
    take = next(item for item in voiceovers if item.get("shot_id") == shot_id)
    _write_wav(directory, shot_id, _wav_bytes(shot.voiceover, take, script.language))


def _wav_bytes(text: str, take: dict[str, Any], language: str) -> bytes:
    return load_take(
        str(take.get("uri") or ""),
        text=text,
        speed=float(take.get("speed") or 1),
        pause_s=float(take.get("pause_s") or 0),
        seed=0,
        language=language,
    )


def _write_wav(directory: Path, shot_id: str, payload: bytes) -> None:
    if not _SHOT.fullmatch(shot_id):
        raise StoryboardError("镜头编号无效")
    path = _inside(directory, directory / "storyboard" / shot_id / "voice.wav")
    atomic_write(path, payload)


def _write_voice_node(directory: Path, script: Script, voiceovers: list[dict[str, Any]]) -> None:
    path = directory / "nodes" / "n06_voiceover.json"
    current = _read_node(directory, "n06_voiceover")
    current["script"] = script.model_dump(mode="json")
    current["voiceovers"] = voiceovers
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, current)


def _write_frame_node(directory: Path, keyframes: list[dict[str, Any]]) -> None:
    current = _read_node(directory, "n08_keyframe")
    current["keyframes"] = keyframes
    path = directory / "nodes" / "n08_keyframe.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, current)


def _write_index(directory: Path, cards: list[dict[str, Any]]) -> None:
    path = _inside(directory, directory / "storyboard" / "index.json")
    _write_json(path, {"cards": cards})


def _read_index(directory: Path) -> dict[str, Any]:
    path = directory / "storyboard" / "index.json"
    if not path.is_file():
        return {"cards": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"cards": []}
    return data if isinstance(data, dict) else {"cards": []}


def _index_card(directory: Path, shot_id: str) -> dict[str, Any] | None:
    for card in _read_index(directory).get("cards") or []:
        if isinstance(card, dict) and card.get("shot_id") == shot_id:
            return card
    return None


def _hash_voices(directory: Path) -> dict[str, str]:
    folder = directory / "storyboard"
    found: dict[str, str] = {}
    if not folder.is_dir():
        return found
    for shot_dir in sorted(path for path in folder.iterdir() if path.is_dir()):
        wav = shot_dir / "voice.wav"
        if _SHOT.fullmatch(shot_dir.name) and wav.is_file():
            found[shot_dir.name] = hashlib.sha256(wav.read_bytes()).hexdigest()
    return found


def _film_state(directory: Path) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for name in ("n04_script", "n05_storyboard", "n06_voiceover", "n08_keyframe"):
        state.update(_read_node(directory, name))
    return state


def _read_node(directory: Path, name: str) -> dict[str, Any]:
    path = directory / "nodes" / f"{name}.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _read_snapshot(directory: Path, project_id: str) -> dict[str, Any]:
    path = directory / "project.json"
    if not path.is_file():
        raise StoryboardError("项目不存在", status=404)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoryboardError("项目状态损坏", status=500) from exc
    if not isinstance(data, dict):
        raise StoryboardError("项目状态损坏", status=500)
    data.setdefault("project_id", project_id)
    return data


def _write_snapshot(directory: Path, snapshot: dict[str, Any]) -> None:
    snapshot.pop("regen_used", None)
    _write_json(directory / "project.json", snapshot)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(path, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode())


def _script(state: dict[str, Any]) -> Script:
    raw = state.get("script")
    if not isinstance(raw, dict):
        raise StoryboardError("还没有分镜")
    return Script.model_validate(raw)


def _voice_list(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _frame_list(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _selected_opening(rows: list[dict[str, Any]], shot_id: str) -> dict[str, Any] | None:
    opening = []
    for row in rows:
        if row.get("shot_id") != shot_id:
            continue
        frame = str((row.get("params") or {}).get("frame") or "first")
        if frame == "first":
            opening.append(row)
    chosen = [row for row in opening if row.get("selected") is True]
    if chosen:
        return chosen[0]
    return opening[0] if opening else None


def _shot_prompts_contain(rows: list[dict[str, Any]], shot_id: str, text: str) -> bool:
    needle = text.strip()
    if len(needle) < 2:
        return False
    for row in rows:
        if row.get("shot_id") != shot_id:
            continue
        params = row.get("params") if isinstance(row.get("params"), dict) else {}
        blob = "\n".join(
            str(params.get(key) or "") for key in ("prompt", "negative_prompt", "voiceover")
        )
        if needle in blob:
            return True
    return False


def _remove_frames(directory: Path, shot_id: str) -> None:
    folder = directory / "storyboard" / shot_id
    if not folder.is_dir():
        return
    for path in folder.glob("frame.*"):
        if path.is_file():
            path.unlink()


def _inside(directory: Path, path: Path) -> Path:
    root = directory.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise StoryboardError("路径无效")
    return resolved
