"""N2 until T15: read a Brand Kit, never create one."""

from __future__ import annotations

import os
from typing import Any

from pydantic import ValidationError

from workers.logging import log_event
from workers.schemas.brand import BrandKit


class BrandReadError(ValueError):
    """The caller supplied a Brand Kit that is not the chapter 5 model."""


def resolve_brand_kit(
    *,
    inline: dict[str, Any] | None,
    brand_id: str | None,
    project_id: str,
    attempt: int,
) -> dict[str, Any] | None:
    """Prefer the kit on the request. Otherwise read ``brand_kits`` when it is reachable.

    A missing kit is not a failure. N4 and later already accept ``brand_kit=None``.
    """

    if inline is not None:
        try:
            kit = BrandKit.model_validate(inline)
        except ValidationError as exc:
            raise BrandReadError(f"brand kit failed validation: {exc}") from exc
        return kit.model_dump(mode="json")
    if not brand_id:
        return None
    loaded = _from_database(brand_id, project_id=project_id, attempt=attempt)
    return loaded


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
    try:
        kit = BrandKit.model_validate(document)
    except ValidationError as exc:
        log_event(
            "n02_brand_kit_invalid",
            project_id=project_id,
            node="n02_brand_kit",
            attempt=attempt,
            error=str(exc)[:300],
        )
        return None
    return kit.model_dump(mode="json")
