"""Picture hold fills a short read. A read that cannot be sped up is flagged."""

from __future__ import annotations

from workers.nodes.n06_voiceover.timing import boost_factor, fit_durations


def test_short_audio_is_padded_to_the_brief() -> None:
    fitted = fit_durations([2.0, 3.0, 5.0], target_s=20)
    audios, holds, durations = zip(*fitted, strict=True)
    assert audios == (2.0, 3.0, 5.0)
    assert all(hold > 0 for hold in holds)
    assert all(duration >= audio for duration, audio in zip(durations, audios, strict=True))
    assert abs(sum(durations) - 20) < 1e-9


def test_audio_inside_five_percent_is_not_stretched() -> None:
    fitted = fit_durations([10.2], target_s=10)
    assert fitted == [(10.2, 0.0, 10.2)]


def test_no_brief_keeps_the_audio_length() -> None:
    assert fit_durations([1.5, 2.5], target_s=None) == [(1.5, 0.0, 1.5), (2.5, 0.0, 2.5)]


def test_modest_speed_up_can_land_on_the_brief() -> None:
    factor = boost_factor([12.0], [0.4], 11.0)
    assert factor is not None
    assert 1 < factor <= 1.15


def test_copy_that_stays_long_cannot_be_sped_into_range() -> None:
    assert boost_factor([40.0, 40.0], [0.0, 0.4], 10.0) is None
