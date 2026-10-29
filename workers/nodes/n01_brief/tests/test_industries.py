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
