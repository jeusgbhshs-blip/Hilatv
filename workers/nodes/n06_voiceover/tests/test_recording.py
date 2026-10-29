"""The user-recording hook calls ASR and is not part of the voiceover run."""

from __future__ import annotations

from workers.nodes.n06_voiceover.recording import align_user_recording


def test_align_user_recording_calls_asr(gateway) -> None:
    out = align_user_recording(
        "oss://takes/boss.wav",
        gateway,
        language="zh",
        project_id="proj-n6",
    )
    assert out["task"] == "asr"
    assert out["audio_uri"] == "oss://takes/boss.wav"
    assert out["text"] == ""
    row = gateway.store.list_logs(project_id="proj-n6")[-1]
    assert row["task"] == "asr"
    assert row["node"] == "n06_voiceover"
    assert row["params"]["user_recording"] is True
