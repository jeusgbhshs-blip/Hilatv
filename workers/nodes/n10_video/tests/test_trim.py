import pytest

from gateway.media_bytes import render_mp4
from workers.media.trim import best_generation_s, plan_trim, probe_duration_s, trim_mp4


def test_generation_interval_is_five_or_ten() -> None:
    assert best_generation_s(4.0, margin=0.2) == 5
    assert best_generation_s(4.8, margin=0.2) == 10
    assert best_generation_s(8.0, margin=0.2) == 10


def test_trim_keeps_head_and_tail_and_matches_duration() -> None:
    source = render_mp4(3, duration_s=5)
    source_s = probe_duration_s(source)
    window = plan_trim(2.0, source_s, margin=0.2)
    assert window["trim_start_s"] >= 0.2
    assert window["tail_margin_s"] > 0
    assert window["trim_end_s"] < source_s
    assert abs((window["trim_end_s"] - window["trim_start_s"]) - 2.0) < 0.02
    trimmed = trim_mp4(source, start_s=window["trim_start_s"], duration_s=2.0)
    assert abs(probe_duration_s(trimmed) - 2.0) < 0.25


def test_plan_rejects_a_clip_with_no_spare_time() -> None:
    with pytest.raises(Exception):
        plan_trim(5.0, 5.0, margin=0.2)
