"""Default advertising-law terms, and explicit lists that still round-trip."""

from __future__ import annotations

from workers.schemas import AD_LAW_EXTREME_WORDS, BrandKit, default_banned_words, find_banned_words
from workers.schemas.tests.conftest import load_fixture

REQUIRED = ("最", "第一", "顶级", "国家级", "最好", "最高级", "最佳")


def test_default_list_contains_ad_law_terms() -> None:
    defaults = default_banned_words()
    for word in REQUIRED:
        assert word in defaults
    assert defaults == list(AD_LAW_EXTREME_WORDS)
    assert len(defaults) == len(set(defaults))


def test_omitted_banned_words_use_the_default_and_are_not_shared() -> None:
    payload = load_fixture("brand_kit.json")
    del payload["banned_words"]
    first = BrandKit.model_validate(payload)
    second = BrandKit.model_validate(payload)
    for word in REQUIRED:
        assert word in first.banned_words
    first.banned_words.append("仅此一家")
    assert "仅此一家" not in second.banned_words
    assert "仅此一家" not in default_banned_words()


def test_explicit_list_is_stored_verbatim() -> None:
    kit = BrandKit.model_validate(load_fixture("brand_kit.json"))
    assert kit.banned_words == ["最好", "第一", "国家级"]
    extended = kit.with_extra_banned_words(["顶级", "最好", "全网最低"])
    assert kit.banned_words == ["最好", "第一", "国家级"]
    assert extended.banned_words == ["最好", "第一", "国家级", "顶级", "全网最低"]


def test_find_banned_words_follows_list_order() -> None:
    text = "我们是国家级第一品牌，效果最好"
    found = find_banned_words(text, default_banned_words())
    assert found[0] == "最"
    assert "第一" in found
    assert "国家级" in found
    assert "最好" in found
    assert "第一品牌" in found
    assert find_banned_words("", ["最"]) == []
    assert find_banned_words("普通介绍", ["最"]) == []
