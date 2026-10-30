"""The initial shot library is original YAML with a no-text constraint."""

from __future__ import annotations

from workers.nodes.n05_storyboard.presets import load_presets, reset_presets


def test_library_covers_the_sample_move() -> None:
    reset_presets()
    presets = load_presets()
    assert len(presets) >= 6
    by_id = {item.id: item for item in presets}
    assert "slow_push_in" in by_id
    for preset in presets:
        assert preset.prompt_fragment.strip()
        assert preset.recommended_model
        lowered = preset.negative_fragment.lower()
        assert "text" in lowered or "文字" in preset.negative_fragment
        assert "logo" in lowered or "Logo" in preset.negative_fragment
        assert not any(ch.isdigit() for ch in preset.prompt_fragment)
        assert preset.status == "试用"
        assert preset.formal is False
        assert preset.tested_runs == 0
