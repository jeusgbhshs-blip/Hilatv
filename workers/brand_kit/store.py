"""File store for one Brand Kit per enterprise. Postgres is a read fallback."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from workers.brand_kit.people import people_for_use, release_kit
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
    folder = _enterprise_folder(record.enterprise_id)
    if folder is None:
        raise BrandReadError("enterprise_id must be a uuid inside the brand store")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "record.json"
    temporary = folder / ".record.json.tmp"
    temporary.write_text(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def load_record(enterprise_id: str) -> BrandRecord | None:
    folder = _enterprise_folder(enterprise_id)
    if folder is None:
        return None
    path = folder / "record.json"
    if not path.is_file() or not _inside(path, folder):
        return None
    return BrandRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))


def load_by_brand_id(brand_id: str, enterprise_id: str) -> BrandRecord | None:
    """Read one enterprise's record. Never scan other enterprises."""

    record = load_record(enterprise_id)
    if record is None:
        return None
    if record.brand_kit.get("brand_id") != brand_id:
        return None
    return record


def write_asset(enterprise_id: str, name: str, data: bytes) -> str:
    folder = _asset_folder(enterprise_id)
    if folder is None or not _safe_name(name):
        raise BrandReadError("asset path is outside the brand store")
    folder.mkdir(parents=True, exist_ok=True)
    path = (folder / name).resolve()
    if not _inside(path, folder):
        raise BrandReadError("asset path is outside the brand store")
    path.write_bytes(data)
    eid = _uuid_text(enterprise_id)
    if eid is None:
        raise BrandReadError("enterprise_id must be a uuid")
    return f"brand://{eid}/{name}"


def read_asset(uri: str, *, enterprise_id: str | None = None) -> bytes | None:
    """Read one asset only for this enterprise, and only from inside its directory."""

    parsed = _parse_uri(uri)
    if parsed is None:
        return None
    owner, name = parsed
    if enterprise_id is not None:
        current = _uuid_text(enterprise_id)
        if current is None or current != owner:
            return None
    folder = _asset_folder(owner)
    if folder is None or not _safe_name(name):
        return None
    path = (folder / name).resolve()
    if not _inside(path, folder) or not path.is_file():
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
    """Prefer an inline kit for this project only. Never write it into the enterprise archive.

    Client-declared consent is ignored. ``brand://`` assets must name this enterprise.
    """

    if inline is not None:
        try:
            kit = BrandKit.model_validate(inline)
        except ValidationError as exc:
            raise BrandReadError(f"brand kit failed validation: {exc}") from exc
        _reject_foreign_uris(kit, enterprise_id)
        return release_kit(kit, trust_consent=False).model_dump(mode="json")
    if enterprise_id:
        record = load_record(enterprise_id)
        if brand_id:
            record = load_by_brand_id(brand_id, enterprise_id)
        if record is not None:
            return export_record(record)["brand_kit"]
    if brand_id and not enterprise_id:
        raise BrandReadError("brand_id lookup requires enterprise_id")
    return None


def export_record(record: BrandRecord) -> dict[str, Any]:
    """Downstream view. Recomputes who may appear. Drops other enterprises' assets."""

    enterprise_id = _uuid_text(record.enterprise_id)
    if enterprise_id is None:
        raise BrandReadError("enterprise_id must be a uuid")
    try:
        kit = BrandKit.model_validate(record.brand_kit)
    except ValidationError as exc:
        raise BrandReadError(f"brand kit failed validation: {exc}") from exc
    locked = _lock_foreign_uris(kit, enterprise_id)
    released = release_kit(locked, trust_consent=True)
    anchors = []
    for item in record.anchors:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "")
        if read_asset(uri, enterprise_id=enterprise_id) is None:
            continue
        anchors.append(item)
    mono = record.mono_black
    if mono.startswith("brand://") and read_asset(mono, enterprise_id=enterprise_id) is None:
        mono = ""
    return {
        "brand_kit": released.model_dump(mode="json"),
        "usable_people": [person.person_id for person in people_for_use(released)],
        "anchors": anchors,
        "mono_black": mono,
        "preferences": list(record.preferences),
    }


def _parse_uri(uri: str) -> tuple[str, str] | None:
    prefix = "brand://"
    if not isinstance(uri, str) or not uri.startswith(prefix):
        return None
    rest = uri[len(prefix) :]
    if not rest or "\\" in rest or ".." in rest or rest.startswith("/"):
        return None
    enterprise_id, separator, name = rest.partition("/")
    if not separator or not _safe_name(name):
        return None
    owner = _uuid_text(enterprise_id)
    if owner is None:
        return None
    return owner, name


def _uuid_text(value: object) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def _enterprise_folder(enterprise_id: str) -> Path | None:
    eid = _uuid_text(enterprise_id)
    if eid is None:
        return None
    root = open_brand_root().resolve()
    folder = (root / eid).resolve()
    if not _inside(folder, root):
        return None
    return folder


def _asset_folder(enterprise_id: str) -> Path | None:
    folder = _enterprise_folder(enterprise_id)
    if folder is None:
        return None
    assets = (folder / "assets").resolve()
    if not _inside(assets, folder):
        return None
    return assets


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_name(name: str) -> bool:
    if not name or name.startswith(".") or ".." in name:
        return False
    return "/" not in name and "\\" not in name


def _iter_uris(kit: BrandKit) -> list[str]:
    found = [kit.logo.primary, kit.logo.mono_white, kit.cta.wechat_qr]
    for product in kit.products:
        found.extend(product.photos)
        found.extend(product.cutouts)
    for person in kit.people:
        found.extend(person.photos)
    return [item for item in found if isinstance(item, str)]


def _reject_foreign_uris(kit: BrandKit, enterprise_id: str | None) -> None:
    current = _uuid_text(enterprise_id) if enterprise_id else None
    for uri in _iter_uris(kit):
        if not uri.startswith("brand://"):
            continue
        parsed = _parse_uri(uri)
        if parsed is None or current is None or parsed[0] != current:
            raise BrandReadError("brand uri is outside this enterprise")


def _lock_foreign_uris(kit: BrandKit, enterprise_id: str) -> BrandKit:
    def lock(uri: str) -> str:
        if not uri.startswith("brand://"):
            return uri
        parsed = _parse_uri(uri)
        if parsed is None or parsed[0] != enterprise_id:
            return "blocked"
        return uri

    logo = kit.logo.model_copy(
        update={"primary": lock(kit.logo.primary), "mono_white": lock(kit.logo.mono_white)}
    )
    products = []
    for product in kit.products:
        products.append(
            product.model_copy(
                update={
                    "photos": [lock(item) for item in product.photos],
                    "cutouts": [lock(item) for item in product.cutouts],
                }
            )
        )
    people = []
    for person in kit.people:
        people.append(person.model_copy(update={"photos": [lock(item) for item in person.photos]}))
    cta = kit.cta.model_copy(update={"wechat_qr": lock(kit.cta.wechat_qr)})
    return kit.model_copy(update={"logo": logo, "products": products, "people": people, "cta": cta})
