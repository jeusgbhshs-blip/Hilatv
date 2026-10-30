"""Line breaks, word boundaries, and alignment against N6 tokens."""

from __future__ import annotations

from gateway.media_bytes import speech_timestamps
from workers.media.packaging import EN_MAX_CHARS, ZH_MAX_CHARS, safe_insets
from workers.nodes.n06_voiceover.schema import WordStamp
from workers.nodes.n13_subtitle.layout import Box, place_subtitle
from workers.nodes.n13_subtitle.segment import (
    alignment_error_ms,
    break_lines,
    highlight_spans,
    stamp_bounds,
)


def _stamps(text: str, language: str) -> list[WordStamp]:
    raw, _duration = speech_timestamps(text, language=language)
    return [WordStamp.model_validate(item) for item in raw]


def test_chinese_lines_stay_within_16_and_keep_words() -> None:
    text = "这台高压柱塞泵以三十兆帕稳定运行，适合连续作业的工厂产线。"
    lexicon = ["柱塞泵", "高压", "兆帕", "工厂", "产线"]
    lines = break_lines(text, _stamps(text, "zh"), language="zh", lexicon=lexicon)
    assert lines
    assert all(sum(1 for char in line.text if not char.isspace()) <= ZH_MAX_CHARS for line in lines)
    assert any("柱塞泵" in line.text for line in lines)
    assert not any(line.text.endswith("柱塞") or line.text.startswith("泵") for line in lines)
    flat = "".join(char for line in lines for char in line.text if not char.isspace())
    source = "".join(char for char in text if not char.isspace())
    assert flat == source


def test_english_lines_stay_within_42_and_keep_30_mpa() -> None:
    text = "Built for 30 MPa every single day inside this busy workshop with a steady hand."
    lines = break_lines(text, _stamps(text, "en"), language="en", lexicon=["30 MPa"])
    assert lines
    assert all(len(line.text) <= EN_MAX_CHARS for line in lines)
    assert any("30 MPa" in line.text for line in lines)
    flat = "".join(char for line in lines for char in line.text if not char.isspace())
    source = "".join(char for char in text if not char.isspace())
    assert flat == source


def test_repeated_word_matches_the_later_occurrence() -> None:
    text = "工厂或检测画面。工厂"
    stamps = _stamps(text, "zh")
    lines = break_lines(text, stamps, language="zh", lexicon=["工厂"])
    last = lines[-1]
    bounds = stamp_bounds(last.text, stamps, near_s=last.start_s)
    assert bounds is not None
    assert alignment_error_ms(last.start_s, last.end_s, bounds[0], bounds[1]) <= 100
    assert bounds[0] > stamp_bounds(last.text, stamps)[0]


def test_alignment_matches_token_bounds() -> None:
    text = "高压柱塞泵每天稳定运行。"
    stamps = _stamps(text, "zh")
    lines = break_lines(text, stamps, language="zh", lexicon=["柱塞泵"])
    for line in lines:
        bounds = stamp_bounds(line.text, stamps)
        assert bounds is not None
        assert alignment_error_ms(line.start_s, line.end_s, bounds[0], bounds[1]) <= 100


def test_keyword_highlight_covers_the_spec_and_the_phone() -> None:
    spans = highlight_spans("压力 30 MPa，电话 0532-88881234", ["30 MPa", "0532-88881234"])
    covered = {item[2] for item in spans}
    assert "30 MPa" in covered or "30" in covered
    assert any("0532-88881234" in item[2] for item in spans)


def test_subject_box_moves_the_subtitle_up() -> None:
    safe = safe_insets(["YouTube"])
    open_space = place_subtitle(safe=safe, subject=None, text_w_ratio=0.4, line_h_ratio=0.09)
    blocked = place_subtitle(
        safe=safe,
        subject=Box(x=0.1, y=0.65, w=0.8, h=0.35),
        text_w_ratio=0.4,
        line_h_ratio=0.09,
    )
    assert blocked.moved
    assert blocked.y_ratio < open_space.y_ratio
    assert blocked.y_ratio + blocked.block_h <= 0.65 + 1e-6


def test_douyin_safe_area_sits_higher_than_youtube() -> None:
    douyin = safe_insets(["抖音"])
    youtube = safe_insets(["YouTube"])
    assert douyin.bottom > youtube.bottom
    assert douyin.right > youtube.right
    both = safe_insets(["抖音", "YouTube"])
    assert both.bottom == douyin.bottom
    assert both.right == max(douyin.right, youtube.right)
