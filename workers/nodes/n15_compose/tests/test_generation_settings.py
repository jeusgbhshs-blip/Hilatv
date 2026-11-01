"""Actual offline picture/audio frames prove explicit aspect and whole-film timing."""

import hashlib
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from gateway.tests.conftest import build_gateway, mock_llm_routes
from workers.media.audio import decode_audio
from workers.media.ffmpeg import playable, probe
from workers.media.packaging import FPS, aspect_size, canvas_size, safe_insets
from workers.media.timing import allocate_frames, duration_budget
from workers.nodes.n06_voiceover.node import run as voiceover
from workers.nodes.n06_voiceover.qa import QAError as VoiceError
from workers.nodes.n12_music.accept import _pattern, fixture, hard_fixture
from workers.nodes.n12_music.align import target_boundaries
from workers.nodes.n12_music.beats import detect_onsets, max_error_ms
from workers.nodes.n12_music.library import select_track
from workers.nodes.n12_music.node import run as music
from workers.nodes.n12_music.picture import measure_picture_cuts
from workers.nodes.n13_subtitle.node import run as subtitles
from workers.nodes.n14_packaging.node import run as packaging
from workers.nodes.n15_compose.node import run as compose
from workers.nodes.n15_compose.qa import QAError
from workers.nodes.n17_deliver.node import run as deliver
from workers.nodes.n17_deliver.qa import QAError as DeliveryError
from workers.nodes.n17_deliver.sample import acceptance_request
from workers.workflow.readiness import readiness
from workers.workflow.store import init_project, save_node, update_snapshot

ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "4:5", "21:9")


@pytest.mark.parametrize("aspect", ASPECTS)
def test_requested_aspect_controls_even_pixels_and_stale_environment(aspect, monkeypatch):
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    width, height = canvas_size(aspect)
    left, right = map(int, aspect.split(":"))
    assert width * right == height * left
    assert width % 2 == height % 2 == 0
    small = aspect_size(aspect, 126)
    monkeypatch.setenv("HILATV_RENDER_WIDTH", str(small[0]))
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", str(small[1]))
    assert canvas_size(aspect) == small
    with pytest.raises(ValueError, match="match"):
        canvas_size(aspect, width=322, height=182)


def test_whole_film_budget_and_speech_minimums_cannot_be_rounded_away():
    budget = duration_budget(15)
    assert (budget.total_frames, budget.body_frames, budget.outro_frames) == (450, 378, 72)
    assert duration_budget(15, intro_s=1.6, outro_s=0).body_frames == 402
    assert (duration_budget(5).body_s, duration_budget(5).outro_s) == (4, 1)
    assert (duration_budget(6).body_s, duration_budget(6).outro_s) == (4, 2)
    with pytest.raises(ValueError, match="4-second"):
        duration_budget(5, outro_s=2.4)
    assert sum(allocate_frames([0.11, 0.23, 0], [1, 2, 1], 378)) == 378
    with pytest.raises(ValueError, match="voiceover"):
        allocate_frames([10, 3], [1, 1], 378)
    with pytest.raises(ValueError, match="no time"):
        duration_budget(2)


def test_beat_search_fails_when_speech_leaves_no_feasible_cut():
    with pytest.raises(ValueError, match="beat-aligned"):
        target_boundaries([0.5, 0.5], [0.49, 0.49], select_track("稳重"), 30)


def test_explicit_budget_rejects_a_long_voice_instead_of_cutting_it(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    gateway = build_gateway(tmp_path, routes=mock_llm_routes())
    source = fixture()
    source["script"]["shots"][0]["voiceover"] = "真实旁白必须完整保留。" * 10
    try:
        with pytest.raises(VoiceError, match="trim_copy"):
            voiceover(
                {
                    "project_id": "too-long",
                    "payload": {
                        "script": source["script"],
                        "brief": source["brief"],
                        "target_duration_s": 5,
                        "intro_s": 0,
                        "outro_s": None,
                    },
                },
                gateway=gateway,
                max_attempts=1,
            )
        assert all(float(row["cost_cny"]) == 0 for row in gateway.store.list_logs())
    finally:
        gateway.store.close()


def test_a_legacy_burned_master_cannot_be_used_as_a_clean_picture(tmp_path, monkeypatch):
    from workers.nodes.n17_deliver.support import build_gateway as delivery_gateway

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    gateway = delivery_gateway(tmp_path / "gw")
    raw = acceptance_request(tmp_path)
    raw["payload"].pop("picture_path")
    try:
        with pytest.raises(DeliveryError, match="clean picture"):
            deliver(raw, gateway=gateway, max_attempts=1)
        assert gateway.store.list_logs() == []
    finally:
        gateway.store.close()


def test_all_nine_export_aspects_decode_at_their_actual_ratio(tmp_path, monkeypatch):
    from workers.nodes.n17_deliver.support import build_gateway as delivery_gateway

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    gateway = delivery_gateway(tmp_path / "gw")
    try:
        result = deliver(
            acceptance_request(
                tmp_path,
                aspect_ratios=list(ASPECTS),
                languages=["zh"],
                long_edge=168,
            ),
            gateway=gateway,
            max_attempts=1,
        )
        assert len(result.payload["versions"]) == len(ASPECTS)
        for version in result.payload["versions"]:
            left, right = map(int, version["aspect_ratio"].split(":"))
            info = probe(Path(version["path"]))
            assert info["width"] * right == info["height"] * left
            playable(Path(version["path"]))
    finally:
        gateway.store.close()


def test_exact_total_keeps_eight_actual_picture_cuts_inside_the_original_beat_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    gateway = build_gateway(tmp_path, routes=mock_llm_routes())
    source = hard_fixture()
    source["script"]["shots"][5]["transition_out"] = "dissolve"
    timing = {"target_duration_s": 15, "intro_s": 0, "outro_s": 2.4}
    try:
        soundtrack = music(
            {
                "project_id": "exact-cuts",
                "payload": {
                    **source,
                    "work_dir": str(tmp_path / "music"),
                    **timing,
                },
            },
            gateway=gateway,
            max_attempts=1,
        ).payload
        board = soundtrack["aligned_script"]
        packed = packaging(
            {
                "project_id": "exact-cuts",
                "payload": {
                    "script": board,
                    "brief": source["brief"],
                    "width": 320,
                    "height": 180,
                    "work_dir": str(tmp_path / "packaging"),
                    **timing,
                },
            }
        ).payload
        clips = [
            {
                "shot_id": shot["shot_id"],
                "path": str(
                    _pattern(
                        tmp_path / "patterns" / (shot["shot_id"] + ".mp4"), index, low_contrast=True
                    )
                ),
            }
            for index, shot in enumerate(board["shots"])
        ]
        result = compose(
            {
                "project_id": "exact-cuts",
                "payload": {
                    "script": board,
                    "brief": source["brief"],
                    "voiceovers": source["voiceovers"],
                    "audio_track": soundtrack["audio_track"],
                    "elements": packed["elements"],
                    "logo_status": packed["logo_status"],
                    "shot_clips": clips,
                    "width": 320,
                    "height": 180,
                    "work_dir": str(tmp_path / "compose"),
                    **timing,
                },
            },
            max_attempts=1,
        ).payload
        actual = measure_picture_cuts(Path(result["exports"]["master"]), tmp_path / "measured")
        assert len(actual.cuts_s) >= 8
        assert actual.error_ms <= 80
        assert result["filters"]["master"].count("xfade=") == 2
        assert abs(probe(Path(result["exports"]["master"]))["duration_s"] - 15) <= 1 / FPS
    finally:
        gateway.store.close()


@pytest.mark.parametrize(
    "aspect,size,target",
    [
        ("4:3", (320, 240), 15),
        ("9:16", (180, 320), 15),
        ("4:3", (320, 240), 5),
        ("9:16", (180, 320), 6),
    ],
)
def test_actual_fifteen_second_movie_has_the_selected_frame_and_complete_audio(
    tmp_path, monkeypatch, aspect, size, target
):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    # A stale 16:9 environment must not silently override these explicit frames.
    monkeypatch.setenv("HILATV_RENDER_WIDTH", "320")
    monkeypatch.setenv("HILATV_RENDER_HEIGHT", "180")
    project_id = "ratio-" + aspect.replace(":", "x")
    init_project(project_id, enterprise_id="00000000-0000-0000-0000-000000000001")
    root = tmp_path / project_id
    routes = (
        mock_llm_routes()
        + """
  - id: content-safety
    task: content_safety
    shot_type: '*'
    language: '*'
    primary: {provider: mock, model: mock-content-safety}
    fallbacks: []
"""
    )
    gateway = build_gateway(root, routes=routes)
    source = fixture()
    if target < 15:
        source["script"]["shots"] = [source["script"]["shots"][index] for index in (0, 2)]
        for index, shot in enumerate(source["script"]["shots"], start=1):
            shot.update(order=index, duration_s=2)
    brief = {**source["brief"], "aspect_ratios": [aspect], "duration_s": target}
    budget = duration_budget(target)
    timing = {"target_duration_s": target, "intro_s": 0, "outro_s": None}
    geometry = {"width": size[0], "height": size[1]}
    try:
        spoken = voiceover(
            {
                "project_id": project_id,
                "payload": {
                    "script": source["script"],
                    "brief": brief,
                    **timing,
                },
            },
            gateway=gateway,
        )
        script, takes = spoken.payload["script"], spoken.payload["voiceovers"]
        assert (
            sum(round(shot["duration_s"] * FPS) for shot in script["shots"]) == budget.body_frames
        )
        soundtrack = music(
            {
                "project_id": project_id,
                "payload": {
                    "script": script,
                    "voiceovers": takes,
                    "brief": brief,
                    "mood": "轻快",
                    "work_dir": str(root / "n12"),
                    **timing,
                },
            },
            gateway=gateway,
        )
        mix = soundtrack.payload
        onsets = detect_onsets(decode_audio(Path(mix["music_bed_path"]).read_bytes()), 48000)
        assert max_error_ms(mix["cut_times_s"], onsets) <= 80
        assert (
            sum(round(shot["duration_s"] * FPS) for shot in mix["aligned_script"]["shots"])
            == budget.body_frames
        )
        captions = subtitles(
            {
                "project_id": project_id,
                "payload": {
                    "script": script,
                    "voiceovers": takes,
                    "brief": brief,
                    "work_dir": str(root / "n13"),
                    **geometry,
                },
            }
        )
        packed = packaging(
            {
                "project_id": project_id,
                "payload": {
                    "script": script,
                    "brief": brief,
                    "work_dir": str(root / "n14"),
                    **timing,
                    **geometry,
                },
            }
        )
        result = compose(
            {
                "project_id": project_id,
                "payload": {
                    "script": script,
                    "brief": brief,
                    "aligned_script": mix["aligned_script"],
                    "voiceovers": takes,
                    "audio_track": mix["audio_track"],
                    "licenses": mix["licensing_summary"]["records"],
                    "cues": captions.payload["cues"],
                    "elements": packed.payload["elements"],
                    "logo_status": packed.payload["logo_status"],
                    "work_dir": str(root / "n15"),
                    **timing,
                    **geometry,
                },
            },
            gateway=gateway,
            max_attempts=1,
        )
        for name, raw in result.payload["exports"].items():
            info = probe(Path(raw))
            assert (info["width"], info["height"]) == size
            assert abs(info["duration_s"] - target) <= 1 / FPS
            playable(Path(raw))
            if name == "clean_picture":
                assert not info["audio_codecs"]
        audio = decode_audio(Path(result.payload["exports"]["master"]).read_bytes())
        assert abs(len(audio) / 48000 - target) <= 1 / FPS
        assert packed.payload["outro_s"] == budget.outro_s
        assert sum(int(value) ** 2 for value in audio[48000:96000]) > 0
        safe = safe_insets(brief["platform"])
        for overlay in result.payload["timeline"]["overlays"]:
            if overlay["kind"] != "subtitle":
                continue
            with Image.open(overlay["path"]) as image:
                assert overlay["x"] >= round(safe.left * size[0])
                assert overlay["x"] + image.width <= round((1 - safe.right) * size[0])
                assert overlay["y"] + image.height <= round((1 - safe.bottom) * size[1])
        save_node(project_id, "n15_compose", result.payload)
        snapshot = update_snapshot(project_id, deliverable=result.payload["exports"]["master"])
        assert readiness(snapshot)["quality_pass"] is False
        assert result.payload["audio_provenance"] == "mock"
        old_digest = hashlib.sha256(
            Path(result.payload["exports"]["master"]).read_bytes()
        ).hexdigest()
        with pytest.raises(QAError, match="frame budget"):
            compose(
                {
                    "project_id": project_id,
                    "payload": {
                        "script": mix["aligned_script"],
                        "target_duration_s": target + 5,
                        "outro_s": budget.outro_s,
                        "work_dir": str(root / "n15"),
                        **geometry,
                    },
                },
                max_attempts=1,
            )
        assert (
            hashlib.sha256(Path(result.payload["exports"]["master"]).read_bytes()).hexdigest()
            == old_digest
        )
        if aspect == "4:3" and target == 15:
            exported = deliver(
                {
                    "project_id": project_id,
                    "payload": {
                        "script": mix["aligned_script"],
                        "brief": brief,
                        "master_path": result.payload["exports"]["master"],
                        "picture_path": result.payload["exports"]["clean_picture"],
                        "source_timeline": result.payload["timeline"],
                        "aspect_ratios": ["9:16"],
                        "languages": ["zh"],
                        "long_edge": 320,
                        "work_dir": str(root / "n17"),
                        **timing,
                    },
                },
                gateway=gateway,
                max_attempts=1,
            )
            version = exported.payload["versions"][0]
            assert "15.0" in Path(version["path"]).name
            assert (version["width"], version["height"]) == (180, 320)
            assert abs(probe(Path(version["path"]))["duration_s"] - 15) <= 1 / FPS
            assert version["qa_status"] == "needs_review"
            assert version["media_provenance"] == "mock"
            # Decode the private source: it contains no burned text layer.
            frame = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    "13.5",
                    "-i",
                    result.payload["exports"]["clean_picture"],
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ],
                check=True,
                capture_output=True,
            ).stdout
            assert len(set(frame[index : index + 3] for index in range(0, len(frame), 3))) < 16
    finally:
        gateway.store.close()
