"""FastAPI application."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.brands import router as brand_router
from app.deliveries import router as delivery_router
from app.logging import log_event
from app.projects import router
from app.settings import get_settings
from workers.workflow.runtime import shutdown_runtime


def web_origins() -> list[str]:
    """Browser origins allowed to call the API. Empty falls back to local Next."""

    raw = os.getenv("HILATV_WEB_ORIGINS")
    if raw is None or not raw.strip():
        raw = "http://localhost:3000,http://127.0.0.1:3000"
    return [item.strip() for item in raw.split(",") if item.strip()]


@asynccontextmanager
async def _lifespan(app: FastAPI):
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
app.include_router(router)
app.include_router(brand_router)
app.include_router(delivery_router)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    log_event("health", service="hilatv-api", env=settings.hilatv_env)
    return {"status": "ok", "service": "hilatv-api", "env": settings.hilatv_env}
