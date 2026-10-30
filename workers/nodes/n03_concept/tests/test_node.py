"""Three concept cards stay apart and avoid banned words."""

from __future__ import annotations

from workers.nodes.n01_brief.industries import INDUSTRY_ORDER, load_industries
from workers.nodes.n03_concept.compose import card_text, compose_directions, pick_structures
from workers.nodes.n03_concept.node import run
from workers.nodes.n03_concept.qa import QAError
from workers.nodes.n03_concept.similarity import cosine
from workers.schemas.brand import default_banned_words, find_banned_words

_BRIEF = {
    "brief_id": "brief-1",
    "raw_input": "给测试泵做一条15秒宣传片",
    "goal": "产品宣传",
    "platform": ["视频号"],
    "duration_s": 15,
    "aspect_ratios": ["9:16"],
    "languages": ["zh"],
    "video_type": "product_showcase",
    "audience": "采购",
    "must_include": [],
    "style": "稳重",
    "assumptions": [],
    "open_questions": [],
}


def test_every_industry_has_three_distinct_directions() -> None:
    banned = default_banned_words()
    templates = load_industries()
    for industry in INDUSTRY_ORDER:
        template = templates[industry]
        structures = pick_structures(template)
        assert len(structures) == 3
        assert len(template.narrative_structures) >= 3
        cards = compose_directions(template, structures, banned=banned)
        texts = [card_text(card) for card in cards]
        for index, left in enumerate(texts):
            assert find_banned_words(left, banned) == []
            for right in texts[index + 1 :]:
                assert cosine(left, right) < 0.85


def test_auto_selection_is_you_pick_and_covers_exist(gateway) -> None:
    result = run(
        {"project_id": "concept", "payload": {"brief": _BRIEF, "selection": None}},
        gateway=gateway,
        max_attempts=1,
    )
    concept = result.payload["concept"]
    assert concept["selection"] == "你帮我选"
    assert concept["auto"] is True
    assert concept["direction"] == "product_showcase"
    assert concept["aspect_ratio"] == "9:16"
    assert result.ok is False
    assert concept["degraded"] is True
    assert concept["text_source"] == "template_fallback"
    assert len(concept["directions"]) == 3
    assert all(item["source"] == "template_fallback" for item in concept["directions"])
    assert all(item["cover_status"] == "not_ready" for item in concept["directions"])
    assert all(item["cover_uri"] == "" for item in concept["directions"])
    assert all(item["cover_preview"] == "" for item in concept["directions"])
    logs = gateway.store.list_logs(project_id="concept")
    prompts = [row["params"]["prompt"] for row in logs if row["task"] == "image"]
    assert len(prompts) == 6
    assert all("no text" in prompt.lower() or "不要出现任何文字" in prompt for prompt in prompts)


def test_explicit_card_is_kept(gateway) -> None:
    preview = run(
        {"project_id": "preview", "payload": {"brief": _BRIEF}},
        gateway=gateway,
        max_attempts=1,
    )
    chosen = preview.payload["concept"]["directions"][1]["direction_id"]
    result = run(
        {"project_id": "picked", "payload": {"brief": _BRIEF, "selection": chosen}},
        gateway=gateway,
        max_attempts=1,
    )
    concept = result.payload["concept"]
    assert concept["auto"] is False
    assert concept["selection"] == chosen
    assert concept["chosen_id"] == chosen


def test_unknown_card_is_rejected(gateway) -> None:
    try:
        run(
            {"project_id": "missing", "payload": {"brief": _BRIEF, "selection": "not-a-card"}},
            gateway=gateway,
            max_attempts=1,
        )
    except QAError as exc:
        assert exc.retryable is False
        assert "未知方案" in str(exc)
    else:
        raise AssertionError("unknown card should fail")
