"""N2 lookup. Building a kit lives in ``workers.brand_kit`` and the N2 node."""

from __future__ import annotations

from typing import Any

from workers.brand_kit.store import BrandReadError, resolve_kit

__all__ = ["BrandReadError", "resolve_brand_kit"]


def resolve_brand_kit(
    *,
    inline: dict[str, Any] | None,
    brand_id: str | None,
    project_id: str,
    attempt: int,
    enterprise_id: str | None = None,
) -> dict[str, Any] | None:
    """Prefer the kit on the request. Otherwise read the enterprise store.

    A missing kit is not a failure. N4 and later already accept ``brand_kit=None``.
    """

    return resolve_kit(
        inline=inline,
        brand_id=brand_id,
        enterprise_id=enterprise_id,
        project_id=project_id,
        attempt=attempt,
    )
