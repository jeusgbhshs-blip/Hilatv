"""素材库：企业隔离的增删查（本地 mock 存储，不接对象存储）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.identity import require_frame_identity, require_identity
from workers.assets import store
from workers.identity.session import Identity
from workers.logging import log_event

router = APIRouter()


@router.get("/v1/assets")
def list_assets(
    kind: str | None = None,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    if kind and kind not in store.KINDS:
        raise HTTPException(status_code=422, detail="素材类型不对")
    return {"assets": store.list_assets(identity.enterprise_id, kind)}


@router.post("/v1/assets")
async def upload_asset(
    file: UploadFile = File(...),
    kind: str = Form("product_image"),
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    if kind not in store.KINDS:
        raise HTTPException(status_code=422, detail="素材类型不对")
    chunks = bytearray()
    try:
        while chunk := await file.read(64 * 1024):
            if len(chunks) + len(chunk) > store.MAX_BYTES:
                raise HTTPException(status_code=413, detail="文件过大")
            chunks.extend(chunk)
    finally:
        await file.close()
    payload = bytes(chunks)
    try:
        meta = store.save_asset(identity.enterprise_id, kind, file.filename or "", payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_event("asset_stored", service="hilatv-api", kind=kind, size=len(payload))
    meta["url"] = f"/v1/assets/{meta['asset_id']}/file"
    return meta


@router.get("/v1/assets/{asset_id}/file")
def asset_file(
    asset_id: str,
    identity: Identity = Depends(require_frame_identity),
) -> FileResponse:
    path = store.asset_file(identity.enterprise_id, asset_id)
    if path is None:
        raise HTTPException(status_code=404, detail="没有这个素材")
    return FileResponse(
        path,
        media_type=None,
        filename=path.name,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/v1/assets/{asset_id}")
def delete_asset(
    asset_id: str,
    identity: Identity = Depends(require_identity),
) -> dict[str, Any]:
    if not store.delete_asset(identity.enterprise_id, asset_id):
        raise HTTPException(status_code=404, detail="没有这个素材")
    return {"deleted": asset_id}
