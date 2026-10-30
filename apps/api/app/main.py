"""FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.logging import log_event
from app.projects import router
from app.settings import get_settings
from workers.workflow.runtime import shutdown_runtime


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    await shutdown_runtime()


app = FastAPI(title="HiLatv API", version="0.1.0", lifespan=_lifespan)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    log_event("health", service="hilatv-api", env=settings.hilatv_env)
    return {"status": "ok", "service": "hilatv-api", "env": settings.hilatv_env}
