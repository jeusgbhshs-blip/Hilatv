import pytest

from workers.workflow.brand import BrandReadError, resolve_brand_kit
from workers.workflow.concept import choose_direction


def _brand() -> dict:
    return {
        "brand_id": "brand-1",
        "company_name": "青岛某某机械有限公司",
        "industry": "manufacturing",
        "logo": {
            "primary": "oss://logo.png",
            "mono_white": "oss://logo-w.png",
            "safe_area_ratio": 0.2,
        },
        "colors": {"primary": "#0A3D91", "secondary": "#FFFFFF", "accent": "#F5A623"},
        "fonts": {"title": "NotoSansSC-Bold", "body": "NotoSansSC-Regular"},
        "products": [],
        "people": [],
        "voice": {"tts_voice": "zh_male_steady", "speed": 1.0},
        "tone": "专业",
        "banned_words": ["最好"],
        "cta": {"phone": "0532-88881234", "website": "https://example.com", "wechat_qr": ""},
    }


def test_inline_kit_is_returned_and_a_missing_one_is_not_an_error() -> None:
    kit = resolve_brand_kit(inline=_brand(), brand_id=None, project_id="p", attempt=1)
    assert kit is not None
    assert kit["brand_id"] == "brand-1"
    assert resolve_brand_kit(inline=None, brand_id=None, project_id="p", attempt=1) is None


def test_invalid_inline_kit_is_rejected() -> None:
    with pytest.raises(BrandReadError):
        resolve_brand_kit(inline={"brand_id": "x"}, brand_id=None, project_id="p", attempt=1)


def test_auto_concept_is_you_pick() -> None:
    concept = choose_direction(
        {
            "video_type": "product_showcase",
            "goal": "外贸获客",
            "duration_s": 15,
            "aspect_ratios": ["16:9"],
        }
    )
    assert concept["selection"] == "你帮我选"
    assert concept["auto"] is True
    assert concept["direction"] == "product_showcase"
    assert concept["aspect_ratio"] == "16:9"
