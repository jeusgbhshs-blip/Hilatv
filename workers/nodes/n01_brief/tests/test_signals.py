from workers.nodes.n01_brief.signals import (
    duration_from_text,
    extract_facts,
    goal_from_text,
    parse_text,
)


def test_duration_units() -> None:
    assert duration_from_text("做个30秒的片子") == 30
    assert duration_from_text("半分钟就够") == 30
    assert duration_from_text("要 4 分钟") == 240
    assert duration_from_text("30 seconds, please") == 30
    assert duration_from_text("没有时长") is None


def test_languages_and_platforms_follow_the_sentence() -> None:
    parsed = parse_text("中英双语，TikTok 和 YouTube，竖屏和横屏")
    assert parsed.languages == ["zh", "en"]
    assert parsed.platforms == ["TikTok", "YouTube"]
    assert parsed.aspects == ["9:16", "16:9"]


def test_explicit_includes_and_style() -> None:
    parsed = parse_text(
        "面向海外工业采购商，风格工业质感、冷色调、稳重，一定要带上 30MPa 和工厂实拍感"
    )
    assert parsed.audience == "海外工业采购商"
    assert parsed.style == "工业质感、冷色调、稳重"
    assert parsed.must_include == ["30MPa", "工厂实拍感"]
    assert goal_from_text("外贸宣传片") == "外贸获客"


def test_pdf_facts_keep_product_and_specs() -> None:
    facts = extract_facts(
        "产品名称：数控机床 XK-200\n卖点：定位精度 0.01mm\n卖点：主轴转速 12000 转\n"
    )
    assert facts.products == ["数控机床 XK-200"]
    assert "0.01mm" in facts.specs
    assert any("12000" in item for item in facts.selling_points)
