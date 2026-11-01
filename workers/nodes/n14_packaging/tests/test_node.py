"""Opening templates, the closing card, and pixel-stable badges."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from workers.media.raster import render_overlay, same_pixels
from workers.nodes.n14_packaging.node import run
from workers.nodes.n14_packaging.qa import QAError, check
from workers.nodes.n14_packaging.schema import PackageElement


def _script(duration: float, cards: list[dict]) -> dict:
    return {
        "script_id": "script-1",
        "brief_id": "brief-1",
        "language": "zh",
        "sections": [],
        "shots": [
            {
                "shot_id": "S01",
                "order": 1,
                "duration_s": duration,
                "purpose": "卖点",
                "visual": "柱塞泵特写，没有文字",
                "shot_size": "close_up",
                "camera": "locked_off",
                "subject_refs": ["product:HP-300"],
                "scene_ref": "scene:workshop",
                "voiceover": "高压柱塞泵稳定运行。",
                "on_screen_text": cards,
                "transition_out": "cut",
                "generation_mode": "image_to_video",
                "status": "pending",
            }
        ],
    }


def _brief(duration: int, platforms: list[str]) -> dict:
    return {
        "brief_id": "brief-1",
        "raw_input": "做一条产品片",
        "goal": "获客",
        "platform": platforms,
        "duration_s": duration,
        "aspect_ratios": ["16:9"],
        "languages": ["zh"],
        "video_type": "product_showcase",
        "audience": "采购",
        "must_include": ["30 MPa"],
        "style": "工业",
        "assumptions": [],
        "open_questions": [],
    }


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


def _run(tmp_path: Path, **payload):
    tmp_path.mkdir(parents=True, exist_ok=True)
    logo = Image.new("RGBA", (100, 50))
    ImageDraw.Draw(logo).rectangle((25, 12, 74, 37), fill=(235, 31, 89, 255))
    source = tmp_path / "source-logo.png"
    logo.save(source)
    brand = _brand()
    brand["logo"]["primary"] = str(source)
    body = {
        "script": _script(4.0, [{"text": "¥12800", "style": "spec_badge", "in": 0.2, "out": 2.0}]),
        "brand_kit": brand,
        "brief": _brief(30, ["YouTube"]),
        "width": 640,
        "height": 360,
        "work_dir": str(tmp_path),
    }
    body.update(payload)
    return run({"project_id": "p-n14", "payload": body})


def test_three_openings_stay_under_two_seconds(tmp_path: Path) -> None:
    for template in ("fade", "rise", "scale"):
        result = _run(tmp_path / template, intro=template)
        elements = check(result)
        assert result.payload["intro_template"] == template
        assert result.payload["intro_s"] <= 2
        assert any(item.kind == "intro_logo" and item.template == template for item in elements)


def test_short_video_skips_the_opening_and_still_closes(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        script=_script(4.0, [{"text": "30 MPa", "style": "spec_badge", "in": 0.2, "out": 2.0}]),
        brief=_brief(12, ["抖音"]),
    )
    elements = check(result)
    assert result.payload["intro_template"] == "none"
    assert result.payload["intro_s"] == 0
    cta = next(item for item in elements if item.kind == "outro_cta")
    logo = next(item for item in elements if item.kind == "outro_logo")
    assert "0532-88881234" in cta.text
    assert logo.kind == "outro_logo"
    assert any(item.kind == "ai_label" and item.text == "AI生成" for item in elements)
    badges = [item.text for item in elements if item.kind == "badge"]
    assert badges == ["30 MPa"]


def test_badge_pixels_match_the_source_text(tmp_path: Path) -> None:
    result = _run(tmp_path, intro="none", corner_logo=False)
    check(result)
    rows = result.payload["elements"]
    badge = next(PackageElement.model_validate(item) for item in rows if item["kind"] == "badge")
    assert badge.text == "¥12800"
    redraw = render_overlay(**badge.spec)
    assert same_pixels(Image.open(badge.png_path), redraw)
    logo = next(item for item in result.payload["elements"] if item["kind"] == "outro_logo")
    source = Image.open(tmp_path / "source-logo.png")
    assert same_pixels(Image.open(logo["png_path"]), source)


def test_instruction_cannot_remove_the_ai_label(tmp_path: Path) -> None:
    with pytest.raises(QAError, match="固定层"):
        _run(tmp_path, instruction="去掉 AI 标识")
    result = _run(tmp_path / "kept", intro="none")
    elements = check(result)
    assert any(item.kind == "ai_label" and item.text == "AI生成" for item in elements)


def test_brand_logo_can_leave_only_the_ending_card(tmp_path: Path) -> None:
    result = _run(tmp_path, brand_logo=False)
    elements = check(result)
    kinds = {item.kind for item in elements}
    assert "outro_logo" in kinds
    assert "outro_cta" in kinds
    assert "intro_logo" not in kinds
    assert "corner_logo" not in kinds
    assert result.payload["brand_logo"] is False


def test_corner_logo_can_be_omitted(tmp_path: Path) -> None:
    result = _run(tmp_path, intro="none", corner_logo=False)
    elements = check(result)
    assert not any(item.kind == "corner_logo" for item in elements)
    with pytest.raises(ValueError):
        run(result.model_dump(mode="json") | {"attempt": 1}, max_attempts=0)
