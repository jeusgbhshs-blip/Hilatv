"""N12 stores aligned durations beside the storyboard. N15 is what reads them."""

from __future__ import annotations

from workers.workflow.activities import music_state_patch, timeline_fields


def test_music_patch_keeps_aligned_durations_off_the_storyboard() -> None:
    patch = music_state_patch(
        {
            "audio_track": {"path": "mix.wav"},
            "licensing_summary": {"records": []},
            "aligned_script": {"shots": [{"shot_id": "S01", "duration_s": 2.0}]},
        }
    )
    assert patch["aligned_script"]["shots"][0]["duration_s"] == 2.0
    assert "script" not in patch


def test_timeline_fields_pass_the_aligned_storyboard_through() -> None:
    state = {
        "script": {"shots": [{"shot_id": "S01", "duration_s": 1.0}]},
        "audio_track": {"path": "mix.wav", "source": "lib", "license": "CC0-1.0"},
        "licensing_summary": {"records": [{"source": "lib", "license": "CC0-1.0"}]},
        "aligned_script": {"shots": [{"shot_id": "S01", "duration_s": 2.0}]},
    }
    fields = timeline_fields(state)
    assert fields["aligned_script"]["shots"][0]["duration_s"] == 2.0
    assert fields["audio_track"]["path"] == "mix.wav"
    assert fields["licenses"][0]["source"] == "lib"
    assert "script" not in fields


def test_timeline_fields_without_music_stay_empty() -> None:
    assert timeline_fields({"script": {"shots": []}}) == {}
