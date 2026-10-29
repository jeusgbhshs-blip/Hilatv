"""FastAPI application. Business routes arrive with later tasks."""

from fastapi import FastAPI

from app.logging import log_event
from app.settings import get_settings

app = FastAPI(title="HiLatv API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    log_event("health", service="hilatv-api", env=settings.hilatv_env)
    return {"status": "ok", "service": "hilatv-api", "env": settings.hilatv_env}
