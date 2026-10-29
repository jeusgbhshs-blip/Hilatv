"""Process settings. Defaults match .env.example so the API boots with no secrets."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    hilatv_env: str = "development"
    hilatv_live: int = 0
    database_url: str = "postgresql://hilatv:hilatv_dev@localhost:5432/hilatv"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "hilatv"
    minio_secret_key: str = "hilatv_dev_secret"
    minio_bucket: str = "hilatv"
    temporal_address: str = "localhost:7233"
    hilatv_budget_cny: float = 0
    hilatv_daily_budget_cny: float = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()
