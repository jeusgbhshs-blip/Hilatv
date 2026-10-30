"""Inline kits stay out of the archive, and brand:// cannot cross enterprises."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.brands import BrandBody, ProductBody
from workers.brand_kit.matting import ReplaceImageError, _open
from workers.brand_kit.people import people_for_use
from workers.brand_kit.store import (
    BrandReadError,
    BrandRecord,
    export_record,
    load_by_brand_id,
    load_record,
    read_asset,
    resolve_kit,
    save_record,
    write_asset,
)
from workers.brand_kit.tests.images import logo_png
from workers.brand_kit.tests.test_reuse import ENTERPRISE, _build
from workers.schemas.brand import BrandKit

OTHER = "44444444-4444-4444-8444-444444444444"
EMPTY = "55555555-5555-4555-8555-555555555555"


def test_inline_kit_does_not_overwrite_the_archive(gateway, brand_dir) -> None:
    assert brand_dir is not None
    _build(gateway)
    original = load_record(ENTERPRISE)
    assert original is not None
    inline = BrandKit.model_validate(original.brand_kit).model_dump(mode="json")
    inline["colors"] = {"primary": "#111111", "secondary": "#222222", "accent": "#333333"}
    inline["people"] = [
        {
            "person_id": "client-person",
            "role": "客户自报",
            "photos": ["secret-face.png"],
            "consent": True,
            "voice_id": "clone",
        }
    ]
    released = resolve_kit(
        inline=inline,
        brand_id=None,
        enterprise_id=ENTERPRISE,
        project_id="inline",
        attempt=1,
    )
    assert released["colors"]["primary"] == "#111111"
    assert released["people"] == []
    assert "secret-face.png" not in str(released)
    assert people_for_use(BrandKit.model_validate(released), trust_consent=False) == []
    kept = load_record(ENTERPRISE)
    assert kept.brand_kit["colors"] == original.brand_kit["colors"]
    assert kept.brand_kit["people"] == original.brand_kit["people"]


def test_cross_enterprise_brand_uri_is_not_readable(gateway, brand_dir) -> None:
    _build(gateway)
    record = load_record(ENTERPRISE)
    owned = record.brand_kit["logo"]["primary"]
    brand_id = record.brand_kit["brand_id"]
    assert read_asset(owned, enterprise_id=ENTERPRISE)
    assert read_asset(owned, enterprise_id=OTHER) is None
    assert load_by_brand_id(brand_id, EMPTY) is None
    assert load_by_brand_id(brand_id, ENTERPRISE).enterprise_id == ENTERPRISE
    with pytest.raises(BrandReadError, match="outside this enterprise"):
        resolve_kit(
            inline=record.brand_kit,
            brand_id=None,
            enterprise_id=OTHER,
            project_id="cross",
            attempt=1,
        )
    save_record(
        BrandRecord(
            enterprise_id=OTHER,
            brand_kit=record.brand_kit,
            mono_black=owned,
            anchors=[{"view": "side", "uri": owned, "on_screen": False, "product_name": "x"}],
            usable_people=["stolen"],
        )
    )
    exported = export_record(load_record(OTHER))
    assert owned not in str(exported)
    assert exported["mono_black"] == ""
    assert exported["anchors"] == []
    assert "stolen" not in exported["usable_people"]


def test_brand_uri_rejects_traversal(brand_dir) -> None:
    assert brand_dir is not None
    payload = logo_png()
    uri = write_asset(ENTERPRISE, "logo.png", payload)
    assert read_asset(uri, enterprise_id=ENTERPRISE) == payload
    assert read_asset(f"brand://{ENTERPRISE}/../../etc/passwd", enterprise_id=ENTERPRISE) is None
    assert read_asset("brand://../x", enterprise_id=ENTERPRISE) is None
    assert read_asset("brand://not-a-uuid/logo.png", enterprise_id=ENTERPRISE) is None
    with pytest.raises(BrandReadError):
        save_record(BrandRecord(enterprise_id="../x", brand_kit={"brand_id": "x"}))


def test_pixel_count_is_rejected_before_decode() -> None:
    header = b"P6\n3000 3000\n255\n"
    with pytest.raises(ReplaceImageError, match="尺寸过大"):
        _open(header)


def test_brand_id_without_enterprise_does_not_query_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unscoped database lookup")

    monkeypatch.setattr("psycopg.connect", explode)
    with pytest.raises(BrandReadError, match="enterprise_id"):
        resolve_kit(
            inline=None,
            brand_id="brand-1",
            enterprise_id=None,
            project_id="p",
            attempt=1,
        )


def test_export_hides_unconsented_archive_person(brand_dir) -> None:
    assert brand_dir is not None
    secret_photo = "oss://hidden/face.jpg"
    secret_voice = "voice-secret-clone"
    kit = {
        "brand_id": "brand-hidden",
        "company_name": "青岛测试机械",
        "industry": "manufacturing",
        "logo": {
            "primary": "oss://logo.png",
            "mono_white": "oss://logo-w.png",
            "safe_area_ratio": 0.2,
        },
        "colors": {"primary": "#0A3D91", "secondary": "#FFFFFF", "accent": "#F5A623"},
        "fonts": {"title": "NotoSansSC-Bold", "body": "NotoSansSC-Regular"},
        "products": [],
        "people": [
            {
                "person_id": "hidden-boss",
                "role": "老板",
                "photos": [secret_photo],
                "consent": False,
                "voice_id": secret_voice,
            },
            {
                "person_id": "shown-engineer",
                "role": "工程师",
                "photos": ["oss://engineer.png"],
                "consent": True,
                "voice_id": None,
            },
        ],
        "voice": {"tts_voice": "zh_male_steady", "speed": 1.0},
        "tone": "专业",
        "banned_words": ["最好"],
        "cta": {"phone": "", "website": "", "wechat_qr": ""},
    }
    save_record(BrandRecord(enterprise_id=ENTERPRISE, brand_kit=kit, usable_people=["hidden-boss"]))
    exported = export_record(load_record(ENTERPRISE))
    rendered = str(exported)
    assert secret_photo not in rendered
    assert secret_voice not in rendered
    assert "hidden-boss" not in rendered
    assert exported["usable_people"] == ["shown-engineer"]
    assert [person["role"] for person in exported["brand_kit"]["people"]] == ["工程师"]
    stored = load_record(ENTERPRISE).brand_kit["people"][0]
    assert stored["photos"] == [secret_photo]
    assert stored["voice_id"] == secret_voice


def test_base64_cap_is_checked_before_decoding() -> None:
    huge = "A" * 8_000_001
    with pytest.raises(ValidationError, match="图片过大"):
        BrandBody(
            enterprise_id=ENTERPRISE,
            company_name="青岛测试机械",
            industry="manufacturing",
            logo_b64=huge,
        )
    with pytest.raises(ValidationError, match="图片过大"):
        ProductBody(name="测试泵", photo_b64=huge)
