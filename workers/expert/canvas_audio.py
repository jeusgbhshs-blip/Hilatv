"""画布配音：单镜 TTS 重新生成，mock 下可试听。

模型调用只走 gateway；配音这一镜不重做画面，也不重跑别的镜头。
"""

from __future__ import annotations

import os
from typing import Any

from workers.expert.charge import reserve
from workers.expert.desk import CanvasDoc, ShotDesk, update_document
from workers.expert.gates import GateError, consent_gate, scrub_brand
from workers.expert.invoke import invoke_node
from workers.expert.operations import GenerationOperation, run_generation
from workers.logging import log_event
from workers.qa.settings import project_dir
from workers.workflow.store import (
    load_checkpoint,
    read_snapshot,
    save_node,
    valid_project_id,
)

_MAX_TEXT = 400


def generate_voiceover(
    project_id: str, shot_id: str, body: dict[str, Any] | None = None, *, gateway: Any | None = None
) -> dict[str, Any]:
    """Regenerate one shot's TTS from its current narration."""

    payload = body or {}
    text = payload.get("text")
    if text is not None:
        text = str(text).strip()
        if not text:
            raise GateError("先写这一镜的话")
        if len(text) > _MAX_TEXT:
            raise GateError("这一镜的话太长了", status=422)
    return run_generation(
        project_id,
        operation_id=payload.get("operation_id"),
        kind="shot_voiceover",
        target=shot_id,
        request={"text": text},
        action=lambda operation: _voiceover(project_id, shot_id, text, operation, gateway=gateway),
    )


def _voiceover(
    project_id: str,
    shot_id: str,
    text: str | None,
    operation: GenerationOperation,
    *,
    gateway: Any | None = None,
) -> dict[str, Any]:
    box: dict[str, Any] = {}

    def mutate(doc: CanvasDoc, state: dict[str, Any], snapshot: dict[str, Any]) -> None:
        if snapshot.get("status") == "running":
            raise GateError("项目仍在运行", status=409)
        script = state.get("script")
        if not isinstance(script, dict):
            raise GateError("还没有分镜，先生成分镜", status=409)
        rows = [item for item in (script.get("shots") or []) if isinstance(item, dict)]
        row = next((item for item in rows if item.get("shot_id") == shot_id), None)
        if row is None:
            raise GateError("没有这个镜头", status=404)
        enterprise_id = snapshot.get("enterprise_id")
        owner = enterprise_id if isinstance(enterprise_id, str) else ""
        consent_gate(owner or None, None)
        if isinstance(state.get("brand_kit"), dict):
            state["brand_kit"] = scrub_brand(state["brand_kit"], owner or None)
        desk = (doc.shots.get(shot_id) or ShotDesk()).model_copy(deep=True)
        if text is not None:
            from workers.expert.shot_action import _narrated_script

            desk.narration = text
            state["script"] = _narrated_script(state, shot_id, text)
            rows = [item for item in (state["script"].get("shots") or []) if isinstance(item, dict)]
            row = next((item for item in rows if item.get("shot_id") == shot_id), row)
        operation.capture(doc.layout_version, {"shot": row, "text": text})
        charged = reserve(project_id, "n06_voiceover", shots=rows, shot_id=shot_id)
        from gateway import get_gateway

        engine = operation.gateway(gateway or get_gateway())
        log_event(
            "canvas_voiceover",
            project_id=project_id,
            node="n06_voiceover",
            shot_id=shot_id,
            charged=charged,
        )
        # Whole-script TTS: shot-scoped runs skip the whole-film clock and would
        # change the shot's duration, breaking the packaging budget. Re-render
        # the takes against the same clock so composition still matches.
        patch = invoke_node(
            "n06_voiceover",
            project_id=project_id,
            state=state,
            snapshot=snapshot,
            gateway=engine,
            enterprise_id=owner or None,
        )
        takes = [item for item in (patch.get("voiceovers") or []) if isinstance(item, dict)]
        for item in takes:
            item["params"] = {
                **(item.get("params") or {}),
                **operation.metadata(),
                **operation.provenance(
                    str(item.get("uri") or ""), node="n06_voiceover", seed=item.get("seed")
                ),
            }
        previous = [item for item in (state.get("voiceovers") or []) if isinstance(item, dict)]
        replaced = {item.get("shot_id") for item in takes}
        merged = [item for item in previous if item.get("shot_id") not in replaced] + takes
        patch["voiceovers"] = merged
        save_node(project_id, "n06_voiceover", patch)
        if text is not None:
            save_node(
                project_id,
                "n04_script",
                {"script": state["script"], "brief": state.get("brief")},
            )
        doc.shots[shot_id] = desk
        doc.layout_version += 1
        box["charged"] = charged

    update_document(project_id, mutate)
    from workers.expert.canvas import build_canvas

    return {
        "project_id": project_id,
        "shot_id": shot_id,
        "charged": box.get("charged") or 0,
        "canvas": build_canvas(project_id),
    }


def voiceover_wav(project_id: str, shot_id: str, *, gateway: Any | None = None) -> bytes:
    """Playable bytes for one shot's voiceover (mock is rebuilt deterministically)."""

    from gateway.media_bytes import render_wav
    from workers.media.audio import audio_bytes, decode_audio, wav_bytes

    if not valid_project_id(project_id) or read_snapshot(project_id) is None:
        raise GateError("项目不存在", status=404)
    state = load_checkpoint(project_id)
    takes = [
        item
        for item in (state.get("voiceovers") or [])
        if isinstance(item, dict) and item.get("shot_id") == shot_id
    ]
    if not takes:
        raise GateError("这一镜还没有配音", status=404)
    take = takes[0]
    script = state.get("script") if isinstance(state.get("script"), dict) else {}
    rows = [item for item in (script.get("shots") or []) if isinstance(item, dict)]
    row = next((item for item in rows if item.get("shot_id") == shot_id), None)
    text = str((row or {}).get("voiceover") or "")
    uri = str(take.get("uri") or "")
    if uri.startswith("mock://") and os.getenv("HILATV_LIVE", "0").strip() != "1":
        data, _stamps, _duration = render_wav(
            text,
            take.get("seed") if isinstance(take.get("seed"), int) else None,
            speed=float(take.get("speed") or 1.0),
            pause_s=float(take.get("pause_s") or 0.0),
            language=script.get("language"),
        )
        return data
    if not uri:
        raise GateError("配音文件不存在", status=404)
    try:
        data = audio_bytes(uri, allowed_roots=[project_dir()], gateway=gateway)
    except Exception as exc:  # noqa: BLE001 - surface as a gate error
        raise GateError("配音文件读不到", status=404) from exc
    try:
        return wav_bytes(decode_audio(data))
    except Exception:  # noqa: BLE001 - already wav/mp3 bytes
        return data
