"""行业模板：列表、画布预览、套用生成项目（复用 templates/industries/*.yaml）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.identity import require_identity
from workers.identity.session import Identity
from workers.workflow.service import start_film

router = APIRouter()

TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "templates" / "industries"


def _load(template_id: str) -> dict[str, Any]:
    path = TEMPLATE_DIR / f"{template_id}.yaml"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="没有这个模板")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(TEMPLATE_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        industry = str(data.get("industry") or path.stem)
        label = str(data.get("label") or industry)
        goal = str(data.get("goal") or "品牌宣传")
        audience = str(data.get("audience") or "目标客户")
        shots = data.get("shot_sequence") if isinstance(data.get("shot_sequence"), list) else []
        rows.append(
            {
                "template_id": industry,
                "industry": industry,
                "title": label,
                "summary": f"{goal} · 面向{audience}",
                "default_sentence": (
                    f"给{label}做一条 {int(data.get('duration_s') or 15)} 秒短视频，{goal}"
                ),
                "shot_count": len(shots),
                "duration_s": int(data.get("duration_s") or 15),
                "platforms": data.get("platforms") or [],
            }
        )
    return rows


@router.get("/v1/templates")
def list_templates(identity: Identity = Depends(require_identity)) -> dict[str, Any]:
    del identity
    return {"templates": _rows()}


@router.get("/v1/templates/{template_id}/canvas")
def template_canvas(
    template_id: str, identity: Identity = Depends(require_identity)
) -> dict[str, Any]:
    del identity
    data = _load(template_id)
    label = str(data.get("label") or template_id)
    shots = data.get("shot_sequence") if isinstance(data.get("shot_sequence"), list) else []
    nodes: list[dict[str, Any]] = [
        {
            "id": "template-brief",
            "kind": "brief",
            "position": {"x": 40, "y": 40},
            "data": {"text": str(data.get("goal") or "")},
            "placeholder": True,
        }
    ]
    edges: list[dict[str, Any]] = []
    for index, item in enumerate(shots):
        node_id = f"template-shot-{index + 1}"
        nodes.append(
            {
                "id": node_id,
                "kind": "shot",
                "position": {"x": 420, "y": 40 + index * 160},
                "data": {"story": str(item), "index": index + 1},
                "placeholder": True,
            }
        )
        edges.append(
            {
                "id": f"template-edge-{index + 1}",
                "source": "template-brief",
                "target": node_id,
                "role": "text",
                "user_created": False,
            }
        )
    nodes.append(
        {
            "id": "template-final",
            "kind": "final",
            "position": {"x": 820, "y": 200},
            "data": {"ai_label": True},
            "placeholder": True,
        }
    )
    return {"nodes": nodes, "edges": edges, "title": label}


class ApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sentence: str = Field(default="", max_length=4000)


@router.post("/v1/templates/{template_id}/apply")
async def apply_template(
    template_id: str,
    body: ApplyBody,
    identity: Identity = Depends(require_identity),
) -> JSONResponse:
    _load(template_id)
    row = next((item for item in _rows() if item["template_id"] == template_id), None)
    sentence = (
        body.sentence.strip() or (row or {}).get("default_sentence") or f"有一条{template_id}短视频"
    )
    project_id = str(__import__("uuid").uuid4())
    await start_film(
        project_id=project_id,
        sentence=sentence,
        enterprise_id=identity.enterprise_id,
        skip_storyboard=True,
    )
    return JSONResponse(
        status_code=202,
        content={"project_id": project_id, "template_id": template_id, "status": "running"},
    )
