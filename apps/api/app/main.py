"""FastAPI application."""

import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.brands import router as brand_router
from app.deliveries import router as delivery_router
from app.expert import router as expert_router
from app.identity import router as identity_router
from app.logging import log_event
from app.projects import router
from app.settings import get_settings
from workers.identity.session import assert_live_session_configured
from workers.workflow.runtime import shutdown_runtime

_MEDIA_QUERY = re.compile(
    r"^/v1/projects/[^/]+/(?:storyboard/[^/]+/frame|expert/media/[^/]+|expert/uploads/[a-f0-9]{32})$"
)


def web_origins() -> list[str]:
    """Browser origins allowed to call the API. Empty falls back to local Next."""

    raw = os.getenv("HILATV_WEB_ORIGINS")
    if raw is None or not raw.strip():
        raw = "http://localhost:3000,http://127.0.0.1:3000"
    return [item.strip() for item in raw.split(",") if item.strip()]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    assert_live_session_configured()
    yield
    await shutdown_runtime()


app = FastAPI(title="HiLatv API", version="0.1.0", lifespan=_lifespan)
WEB_ORIGINS = web_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=WEB_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(identity_router)
app.include_router(router)
app.include_router(brand_router)
app.include_router(delivery_router)
app.include_router(expert_router)


@app.middleware("http")
async def reject_client_enterprise_id(request: Request, call_next):
    """enterprise_id is never a query parameter. The session names the enterprise."""

    if "enterprise_id" in request.query_params:
        return JSONResponse(status_code=422, content={"detail": "enterprise_id 不能由请求指定"})
    if "session" in request.query_params and not _MEDIA_QUERY.match(request.url.path):
        return JSONResponse(status_code=422, content={"detail": "session 查询参数只用于画面"})
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    log_event("health", service="hilatv-api", env=settings.hilatv_env)
    return {"status": "ok", "service": "hilatv-api", "env": settings.hilatv_env}
