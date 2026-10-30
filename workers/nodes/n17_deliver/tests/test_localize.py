"""English is a rewrite of the facts, not a copy of the Chinese master."""

from __future__ import annotations

from workers.nodes.n17_deliver.cuts import keep_for_duration
from workers.nodes.n17_deliver.localize import localize
from workers.nodes.n17_deliver.sample import storyboard
from workers.schemas.brief import Brief
from workers.schemas.script import Script


def test_mock_llm_still_localizes_to_english(gateway) -> None:
    script_raw, brief_raw, _tracks, _durations = storyboard()
    master = Script.model_validate(script_raw)
    brief = Brief.model_validate(brief_raw)
    script, prompt = localize(
        master,
        brief,
        None,
        "en",
        gateway=gateway,
        project_id="p",
        attempt=1,
    )
    assert "on-screen text" in prompt
    assert script.language == "en"
    assert script.shots[0].voiceover != master.shots[0].voiceover
    assert any("a" <= char.lower() <= "z" for char in script.shots[0].voiceover)


def test_short_cut_keeps_the_hook() -> None:
    script_raw, _brief, _tracks, _durations = storyboard()
    master = Script.model_validate(script_raw)
    shots = [shot.model_copy(update={"duration_s": 4.0}) for shot in master.shots]
    kept = keep_for_duration(shots, 1.0)
    assert [item.shot.shot_id for item in kept] == ["S01"]
    assert kept[0].duration_s == 1.0
    both = keep_for_duration(shots, 8.0)
    assert [item.shot.shot_id for item in both] == ["S01", "S02"]
