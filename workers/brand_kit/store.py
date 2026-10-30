"""File store for one Brand Kit per enterprise. Postgres is a read fallback."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from workers.logging import log_event
from workers.schemas.brand import BrandKit


class BrandReadError(ValueError):
    """The caller supplied a Brand Kit that is not the chapter 5 model."""

    retryable = False


class BrandRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enterprise_id: str
    brand_kit: dict[str, Any]
    mono_black: str = ""
    anchors: list[dict[str, Any]] = Field(default_factory=list)
    preferences: list[dict[str, Any]] = Field(default_factory=list)
    usable_people: list[str] = Field(default_factory=list)


def open_brand_root() -> Path:
    override = os.getenv("HILATV_BRAND_DIR", "").strip()
    if override:
        return Path(override)
    project = os.getenv("HILATV_PROJECT_DIR", "").strip()
    base = Path(project) if project else Path(tempfile.gettempdir()) / "hilatv-projects"
    return base / "_brands"


def save_record(record: BrandRecord) -> None:
    folder = open_brand_root() / record.enterprise_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "record.json"
    temporary = folder / ".record.json.tmp"
    temporary.write_text(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def load_record(enterprise_id: str) -> BrandRecord | None:
    path = open_brand_root() / enterprise_id / "record.json"
    if not path.is_file():
        return None
    return BrandRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_by_brand_id(brand_id: str) -> BrandRecord | None:
    root = open_brand_root()
    if not root.is_dir():
        return None
    for child in root.iterdir():
        path = child / "record.json"
        if not path.is_file():
            continue
        try:
            record = BrandRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValidationError, json.JSONDecodeError):
            continue
        if record.brand_kit.get("brand_id") == brand_id:
            return record
    return None


def write_asset(enterprise_id: str, name: str, data: bytes) -> str:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("bad asset name")
    folder = open_brand_root() / enterprise_id / "assets"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return f"brand://{enterprise_id}/{name}"


def read_asset(uri: str) -> bytes | None:
    parsed = _parse_uri(uri)
    if parsed is None:
        return None
    enterprise_id, name = parsed
    path = open_brand_root() / enterprise_id / "assets" / name
    if not path.is_file():
        return None
    return path.read_bytes()


def resolve_kit(
    *,
    inline: dict[str, Any] | None,
    brand_id: str | None,
    enterprise_id: str | None,
    project_id: str,
    attempt: int,
) -> dict[str, Any] | None:
    """Prefer the kit on the request. Otherwise read the enterprise file, then Postgres.

    A missing kit is not a failure. Saving happens when an inline kit names an enterprise,
    so the next project can reuse it without uploading again.
    """

    if inline is not None:
        try:
            kit = BrandKit.model_validate(inline)
        except ValidationError as exc:
            raise BrandReadError(f"brand kit failed validation: {exc}") from exc
        dumped = kit.model_dump(mode="json")
        if enterprise_id:
            _remember(enterprise_id, dumped)
        return dumped
    if enterprise_id:
        record = load_record(enterprise_id)
        if record is not None:
            return _validated(record.brand_kit, project_id=project_id, attempt=attempt)
    if brand_id:
        record = load_by_brand_id(brand_id)
        if record is not None:
            return _validated(record.brand_kit, project_id=project_id, attempt=attempt)
        return _from_database(brand_id, project_id=project_id, attempt=attempt)
    return None


def _remember(enterprise_id: str, kit: dict[str, Any]) -> None:
    existing = load_record(enterprise_id)
    save_record(
        BrandRecord(
            enterprise_id=enterprise_id,
            brand_kit=kit,
            mono_black=existing.mono_black if existing else "",
            anchors=existing.anchors if existing else [],
            preferences=existing.preferences if existing else [],
            usable_people=existing.usable_people if existing else [],
        )
    )


def _validated(document: dict[str, Any], *, project_id: str, attempt: int) -> dict[str, Any] | None:
    try:
        return BrandKit.model_validate(document).model_dump(mode="json")
    except ValidationError as exc:
        log_event(
            "n02_brand_kit_invalid",
            project_id=project_id,
            node="n02_brand_kit",
            attempt=attempt,
            error=str(exc)[:300],
        )
        return None


def _from_database(brand_id: str, *, project_id: str, attempt: int) -> dict[str, Any] | None:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return None
    try:
        import psycopg
    except ImportError:
        return None
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            row = conn.execute(
                "SELECT document FROM brand_kits WHERE brand_id = %s",
                (brand_id,),
            ).fetchone()
    except Exception as exc:
        log_event(
            "n02_brand_kit_unavailable",
            project_id=project_id,
            node="n02_brand_kit",
            attempt=attempt,
            error=str(exc)[:300],
        )
        return None
    if row is None:
        return None
    document = row[0]
    if isinstance(document, str):
        document = json.loads(document)
    return _validated(document, project_id=project_id, attempt=attempt)


def _parse_uri(uri: str) -> tuple[str, str] | None:
    prefix = "brand://"
    if not uri.startswith(prefix):
        return None
    rest = uri[len(prefix) :]
    enterprise_id, _, name = rest.partition("/")
    if not enterprise_id or not name or "/" in name or ".." in name:
        return None
    return enterprise_id, name
