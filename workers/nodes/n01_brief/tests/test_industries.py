from workers.nodes.n01_brief.industries import INDUSTRY_ORDER, load_industries
from workers.nodes.n01_brief.platforms import aspects_match


def test_six_industry_templates_match_platforms() -> None:
    templates = load_industries()
    assert tuple(templates) == INDUSTRY_ORDER
    for industry, template in templates.items():
        assert template.industry == industry
        assert aspects_match(template.platforms, template.aspect_ratios)
        assert template.video(template.default_video_type).id == template.default_video_type
        if len(template.video_types) > 1:
            assert template.clarify_question
            labels = [item.label for item in template.video_types]
            assert template.default_video.label in labels


def test_home_and_plant_words_route_to_a_product_industry() -> None:
    from workers.nodes.n01_brief.industries import detect_industry

    # 一盆植物不该被当成制造业，否则画面会变成工厂产品。
    assert detect_industry("给一盆虎皮兰做一条 6 秒短视频，绿色植物，室内自然光") == "ecommerce"
    assert detect_industry("家居摆件产品展示，绿植搭配") == "ecommerce"
    assert detect_industry("数控机床工厂车间") == "manufacturing"
