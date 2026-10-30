"""Degraded concepts and raw portraits never become a passing delivery."""

from pathlib import Path

from workers.nodes.n18_revision.brand_use import gate_brand
from workers.nodes.n18_revision.concept_gate import classify_concept, delivery_passes
from workers.schemas.brand import BrandKit


def _person_kit() -> BrandKit:
    return BrandKit.model_validate(
        {
            "brand_id": "brand-1",
            "company_name": "示例公司",
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
                    "person_id": "person-1",
                    "role": "工程师",
                    "photos": ["oss://face.png"],
                    "consent": True,
                    "voice_id": "clone-voice",
                }
            ],
            "voice": {"tts_voice": "zh_male_steady", "speed": 1.0},
            "tone": "专业",
            "banned_words": ["最好"],
            "cta": {"phone": "0532-88881234", "website": "https://example.com", "wechat_qr": ""},
        }
    )


def test_inline_kit_drops_people_even_when_consent_is_checked() -> None:
    released = gate_brand(_person_kit(), from_archive=False)
    assert released is not None
    assert released.people == []
    dumped = released.model_dump(mode="json")
    assert "clone-voice" not in str(dumped)
    assert "oss://face.png" not in str(dumped)


def test_revision_code_does_not_read_people_off_a_raw_kit() -> None:
    root = Path("workers/nodes/n18_revision")
    for path in root.rglob("*.py"):
        if path.name == "brand_use.py" or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert ".people" not in text
        assert "people_for_use" not in text
    revise = Path("workers/workflow/revise.py").read_text(encoding="utf-8")
    assert ".people" not in revise
    assert "people_for_use" not in revise


def test_template_fallback_http_body_is_not_a_pass() -> None:
    body = {
        "ok": False,
        "concept": {
            "degraded": True,
            "text_source": "template_fallback",
            "directions": [
                {"source": "template_fallback"},
                {"source": "template_fallback"},
                {"source": "template_fallback"},
            ],
        },
    }
    view = classify_concept(body)
    assert view.degraded is True
    assert view.ok is False
    assert view.text_source == "template_fallback"
    reviewed = [
        {"shot_id": "S01", "visual_reviewed": True, "quality_pass": True},
        {"shot_id": "S02", "visual_reviewed": True, "quality_pass": True},
    ]
    assert delivery_passes(reviewed, body) is False


def test_unreviewed_regen_is_not_a_pass_even_without_a_concept() -> None:
    shots = [{"shot_id": "S02", "visual_reviewed": False, "quality_pass": False}]
    assert delivery_passes(shots, None) is False
    forced = [{"shot_id": "S02", "visual_reviewed": False, "quality_pass": True}]
    assert delivery_passes(forced, None) is False
