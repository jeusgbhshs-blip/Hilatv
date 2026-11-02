"""分镜表编辑：剧本/分镜的读取、单镜修改、增删排序、提示词预览。

核心脚本仍存在 n05_storyboard 节点里（流水线复用同一个 Script）；
界面层的扩展字段（光线/氛围/连续性/生成参数）放在项目目录的
script_ext.json，避免改动管线 schema 影响已合并的节点。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from workers.expert.gates import GateError
from workers.expert.seedance_prompt import STYLE_WORDS, compile_script
from workers.workflow.store import (
    load_checkpoint,
    locked_project,
    project_path,
    read_snapshot,
    save_node,
    valid_project_id,
)

_CORE = {
    "duration_s",
    "purpose",
    "visual",
    "shot_size",
    "camera",
    "voiceover",
    "transition_out",
}
_EXT = {
    "lighting",
    "mood",
    "continuity_notes",
    "sfx",
    "bgm_mood",
    "generation",
    "action",
    "emotion",
    "camera_angle",
    "color",
    "visual_effect",
    "bgm",
    "characters",
    "reference",
}
_TEXT_MAX = {"purpose": 200, "visual": 1200, "shot_size": 40, "camera": 60, "voiceover": 400}


def _ext_path(project_id: str) -> Path:
    return project_path(project_id) / "script_ext.json"


def _read_ext(project_id: str) -> dict[str, Any]:
    path = _ext_path(project_id)
    if not path.is_file():
        return {"revision": 0, "meta": {}, "shots": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"revision": 0, "meta": {}, "shots": {}}
    if not isinstance(data, dict):
        return {"revision": 0, "meta": {}, "shots": {}}
    data.setdefault("revision", 0)
    data.setdefault("meta", {})
    data.setdefault("shots", {})
    return data


def _write_ext(project_id: str, data: dict[str, Any]) -> None:
    path = _ext_path(project_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _script_path(project_id: str):
    return project_path(project_id) / "nodes" / "n05_storyboard.json"


def _read_script(project_id: str) -> dict[str, Any]:
    """n05_storyboard 是分镜的权威来源（后续节点也带 script 副本，会覆盖 checkpoint）。"""

    path = _script_path(project_id)
    if path.is_file():
        try:
            patch = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            patch = {}
        script = patch.get("script") if isinstance(patch, dict) else None
        # 兼容历史写法：个别版本把 {"script": {...}} 又包了一层。
        if isinstance(script, dict) and isinstance(script.get("script"), dict):
            script = script["script"]
        cleaned = _clean_script(script)
        if cleaned is not None:
            return cleaned
    state = load_checkpoint(project_id)
    script = state.get("script")
    cleaned = _clean_script(script)
    if cleaned is None:
        raise GateError("还没有分镜，先生成分镜", status=409)
    return cleaned


def _clean_script(script: object) -> dict[str, Any] | None:
    if not isinstance(script, dict) or not isinstance(script.get("shots"), list):
        return None
    valid = [
        item
        for item in script["shots"]
        if isinstance(item, dict) and isinstance(item.get("shot_id"), str) and item.get("shot_id")
    ]
    if not valid:
        return None
    script["shots"] = valid
    return script


def _script(project_id: str) -> dict[str, Any]:
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    return _read_script(project_id)


def _save_script(project_id: str, script: dict[str, Any]) -> None:
    """保存权威分镜，并同步其它节点里的 script 副本，避免 checkpoint 读到旧镜头。"""

    from workers.workflow.contract import PIPELINE

    save_node(project_id, "n05_storyboard", {"script": script})
    nodes = project_path(project_id) / "nodes"
    for name in PIPELINE:
        if name == "n05_storyboard":
            continue
        path = nodes / f"{name}.json"
        if not path.is_file():
            continue
        try:
            patch = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(patch, dict) and "script" in patch:
            patch["script"] = script
            path.write_text(json.dumps(patch, ensure_ascii=False, indent=2), encoding="utf-8")


def _guard(snapshot: dict[str, Any]) -> None:
    if snapshot.get("status") == "running":
        raise GateError("项目正在生成，请等这一轮结束再改分镜", status=409)


def _public(project_id: str) -> dict[str, Any]:
    script = _script(project_id)
    ext = _read_ext(project_id)
    shots = [item for item in script["shots"] if isinstance(item, dict)]
    shots.sort(key=lambda item: int(item.get("order") or 0))
    compiled = compile_script(
        shots,
        meta=ext.get("meta") or {},
        exts=ext.get("shots") or {},
    )
    rows = []
    for shot, prompt in zip(shots, compiled, strict=True):
        shot_id = str(shot.get("shot_id"))
        row = dict(shot)
        row["ext"] = (ext.get("shots") or {}).get(shot_id) or {}
        row["prompt"] = prompt
        rows.append(row)
    return {
        "project_id": project_id,
        "revision": int(ext.get("revision") or 0),
        "meta": ext.get("meta") or {},
        "style_bible": (ext.get("meta") or {}).get("style_bible") or "写实电影感",
        "styles": list(STYLE_WORDS),
        "shots": rows,
    }


def load_script(project_id: str) -> dict[str, Any]:
    return _public(project_id)


def update_meta(project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    with locked_project(project_id):
        snapshot = read_snapshot(project_id) or {}
        _guard(snapshot)
        ext = _read_ext(project_id)
        meta = dict(ext.get("meta") or {})
        allowed = {"title", "genre", "style_bible", "aspect_ratio", "language", "script_text"}
        for key in allowed:
            if key in body:
                value = body[key]
                if value is None or str(value).strip() == "":
                    meta.pop(key, None)
                else:
                    limit = 20000 if key == "script_text" else 120
                    meta[key] = str(value).strip()[:limit]
        if meta.get("style_bible") not in STYLE_WORDS:
            meta["style_bible"] = meta.get("style_bible") or "写实电影感"
        ext["meta"] = meta
        ext["revision"] = int(ext.get("revision") or 0) + 1
        _write_ext(project_id, ext)
    return _public(project_id)


def patch_shot(project_id: str, shot_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    with locked_project(project_id):
        snapshot = read_snapshot(project_id) or {}
        _guard(snapshot)
        script = _script(project_id)
        rows = [item for item in script["shots"] if isinstance(item, dict)]
        target = next((item for item in rows if item.get("shot_id") == shot_id), None)
        if target is None:
            raise GateError("没有这个镜头", status=404)
        expected = body.get("revision")
        ext = _read_ext(project_id)
        if isinstance(expected, int) and expected != int(ext.get("revision") or 0):
            raise GateError("分镜已被修改，请刷新后再保存", status=409)
        for key, value in body.items():
            if key in {"revision", "shot_id", "ext"}:
                continue
            if key == "duration_s":
                try:
                    duration = float(value)
                except (TypeError, ValueError) as exc:
                    raise GateError("时长必须是数字", status=422) from exc
                if not 1 <= duration <= 60:
                    raise GateError("单镜时长要在 1–60 秒之间", status=422)
                target["duration_s"] = round(duration, 3)
                continue
            if key == "on_screen_text":
                if not isinstance(value, list):
                    raise GateError("字幕格式不对", status=422)
                target["on_screen_text"] = value
                continue
            if key in _CORE:
                text = str(value if value is not None else "").strip()
                if (
                    key in {"purpose", "visual", "shot_size", "camera", "transition_out"}
                    and not text
                ):
                    raise GateError("这一项不能为空", status=422)
                limit = _TEXT_MAX.get(key, 200)
                target[key] = text[:limit]
        incoming = body.get("ext")
        if incoming is not None:
            if not isinstance(incoming, dict):
                raise GateError("扩展字段格式不对", status=422)
            current = dict((ext.get("shots") or {}).get(shot_id) or {})
            for key in _EXT:
                if key in incoming:
                    value = incoming[key]
                    if key == "generation" and isinstance(value, dict):
                        current["generation"] = {
                            k: v
                            for k, v in value.items()
                            if k in {"model", "ratio", "resolution", "negative"}
                        }
                    elif key in {"sfx"} and isinstance(value, list):
                        current["sfx"] = [str(item)[:80] for item in value[:12]]
                    elif key == "characters" and isinstance(value, list):
                        entries = []
                        for item in value[:4]:
                            if isinstance(item, dict):
                                entries.append(
                                    {
                                        "name": str(item.get("name") or "")[:40],
                                        "desc": str(item.get("desc") or "")[:600],
                                    }
                                )
                        current["characters"] = entries
                    elif key == "reference" and isinstance(value, dict):
                        current["reference"] = {
                            name: str(value.get(name) or "")[:200]
                            for name in ("first_frame", "role_sheet", "scene_anchor")
                        }
                    else:
                        current[key] = str(value or "").strip()[:600]
            (ext.setdefault("shots", {}))[shot_id] = current
        script["shots"] = rows
        _save_script(project_id, script)
        ext["revision"] = int(ext.get("revision") or 0) + 1
        _write_ext(project_id, ext)
    return _public(project_id)


def bind_reference(project_id: str, shot_id: str, slot: str, upload_id: str) -> dict[str, Any]:
    """给这一镜绑定参考图槽位（首帧/角色卡/场景锚点）。"""

    if slot not in {"first_frame", "role_sheet", "scene_anchor"}:
        raise GateError("未知的参考图槽位", status=422)
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    with locked_project(project_id):
        snapshot = read_snapshot(project_id) or {}
        _guard(snapshot)
        script = _script(project_id)
        if not any(item.get("shot_id") == shot_id for item in script["shots"]):
            raise GateError("没有这个镜头", status=404)
        ext = _read_ext(project_id)
        current = dict((ext.get("shots") or {}).get(shot_id) or {})
        reference = dict(current.get("reference") or {})
        reference[slot] = str(upload_id)
        current["reference"] = reference
        (ext.setdefault("shots", {}))[shot_id] = current
        ext["revision"] = int(ext.get("revision") or 0) + 1
        _write_ext(project_id, ext)
    return _public(project_id)


def add_shot(project_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    with locked_project(project_id):
        snapshot = read_snapshot(project_id) or {}
        _guard(snapshot)
        script = _script(project_id)
        rows = [item for item in script["shots"] if isinstance(item, dict)]
        rows.sort(key=lambda item: int(item.get("order") or 0))
        after = str(body.get("after_shot_id") or "")
        index = next(
            (i for i, item in enumerate(rows) if item.get("shot_id") == after), len(rows) - 1
        )
        template = dict(rows[index] if rows else {})
        used = {int(item.get("order") or 0) for item in rows}
        order = max(used or {0}) + 1
        shot_id = f"S{order:02d}"
        while any(item.get("shot_id") == shot_id for item in rows):
            order += 1
            shot_id = f"S{order:02d}"
        new_shot = {
            **template,
            "shot_id": shot_id,
            "order": order,
            "duration_s": 5.0,
            "purpose": template.get("purpose") or "新镜头",
            "visual": template.get("visual") or "待补充画面描述",
            "voiceover": "",
            "on_screen_text": [],
            "status": "pending",
        }
        rows.insert(index + 1, new_shot)
        for position, item in enumerate(rows, 1):
            item["order"] = position
        script["shots"] = rows
        _save_script(project_id, script)
        ext = _read_ext(project_id)
        ext["revision"] = int(ext.get("revision") or 0) + 1
        _write_ext(project_id, ext)
    return _public(project_id)


def delete_shot(project_id: str, shot_id: str) -> dict[str, Any]:
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    with locked_project(project_id):
        snapshot = read_snapshot(project_id) or {}
        _guard(snapshot)
        script = _script(project_id)
        rows = [item for item in script["shots"] if isinstance(item, dict)]
        rows = [item for item in rows if item.get("shot_id") != shot_id]
        if len(rows) == 0:
            raise GateError("至少保留一个镜头", status=422)
        rows.sort(key=lambda item: int(item.get("order") or 0))
        for position, item in enumerate(rows, 1):
            item["order"] = position
        script["shots"] = rows
        _save_script(project_id, script)
        ext = _read_ext(project_id)
        (ext.get("shots") or {}).pop(shot_id, None)
        ext["revision"] = int(ext.get("revision") or 0) + 1
        _write_ext(project_id, ext)
    return _public(project_id)


def reorder_shots(project_id: str, shot_ids: list[str]) -> dict[str, Any]:
    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    with locked_project(project_id):
        snapshot = read_snapshot(project_id) or {}
        _guard(snapshot)
        script = _script(project_id)
        rows = [item for item in script["shots"] if isinstance(item, dict)]
        known = {str(item.get("shot_id")) for item in rows}
        if set(shot_ids) != known or len(shot_ids) != len(known):
            raise GateError("排序要包含全部镜头且不能重复", status=422)
        by_id = {str(item.get("shot_id")): item for item in rows}
        ordered = [by_id[shot_id] for shot_id in shot_ids]
        for position, item in enumerate(ordered, 1):
            item["order"] = position
        script["shots"] = ordered
        _save_script(project_id, script)
        ext = _read_ext(project_id)
        ext["revision"] = int(ext.get("revision") or 0) + 1
        _write_ext(project_id, ext)
    return _public(project_id)
