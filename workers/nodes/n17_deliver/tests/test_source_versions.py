"""Actual exports retain earlier sources and retry with a stable identity."""

import copy
import hashlib
import subprocess
from pathlib import Path

import pytest

from workers.media.ffmpeg import encode_plate, playable
from workers.nodes.n15_compose.schema import Timeline, VideoClip
from workers.nodes.n17_deliver.node import run
from workers.nodes.n17_deliver.qa import QAError
from workers.nodes.n17_deliver.sample import acceptance_request
from workers.nodes.n17_deliver.schema import N17Input
from workers.nodes.n17_deliver.source import file_hash, pin_source, source_key


@pytest.mark.parametrize("change", ["picture", "script"])
def test_a_new_source_keeps_old_bytes_and_same_source_retries_keep_their_id(
    tmp_path, gateway, monkeypatch, change
):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    raw = acceptance_request(
        tmp_path,
        languages=["zh"],
        aspect_ratios=["16:9"],
        long_edge=160,
        with_tracks=False,
    )
    first = run(raw, gateway=gateway, max_attempts=1).payload["versions"][0]
    first_path = Path(first["path"])
    first_bytes = first_path.read_bytes()
    old_color = _color(first_path)
    changed = copy.deepcopy(raw)
    if change == "picture":
        encode_plate(
            Path(raw["payload"]["picture_path"]),
            rgb=(16, 48, 192),
            width=320,
            height=180,
            frames=60,
            fps=30,
        )
    else:
        changed["payload"]["script"]["shots"][0]["voiceover"] = "另一台柱塞泵。"
    second = run(changed, gateway=gateway, max_attempts=1).payload["versions"][0]
    assert second["version_id"] != first["version_id"]
    assert second["source_key"] != first["source_key"]
    assert second["path"] != first["path"]
    assert first_path.read_bytes() == first_bytes
    assert second["source_media_hash"] == file_hash(Path(raw["payload"]["picture_path"]))
    assert (second["source_media_hash"] != first["source_media_hash"]) is (change == "picture")
    if change == "picture":
        new_color = _color(Path(second["path"]))
        assert sum(abs(a - b) for a, b in zip(old_color, new_color, strict=True)) > 30
    playable(first_path)
    playable(Path(second["path"]))
    retried = run(changed, gateway=gateway, max_attempts=1).payload["versions"][0]
    assert retried["version_id"] == second["version_id"]
    assert retried["source_key"] == second["source_key"]
    assert retried["path"] == second["path"]
    assert first_path.read_bytes() == first_bytes


def test_temporary_paths_and_produce_ids_do_not_change_the_source_identity(tmp_path):
    raw = acceptance_request(tmp_path, languages=["zh"], aspect_ratios=["4:3"])
    payload = N17Input.model_validate(raw["payload"])
    timeline = Timeline(
        width=320,
        height=180,
        duration_s=2,
        lut_path="/old/lut",
        work_dir="/old/work",
        clips=[VideoClip(clip_id="S01", path="/old/plate", start_s=0, duration_s=2)],
        audio=[],
        overlays=[],
        produce_ids={"master": "random-old-id"},
    )
    digest = file_hash(Path(payload.picture_path))
    config = {"long_edge": 160, "aspects": ["4:3"]}
    original = source_key(payload, digest, timeline, config)
    moved_payload = payload.model_copy(
        update={
            "work_dir": "/another/work",
            "master_path": "/another/master",
            "picture_path": "/another/picture",
        }
    )
    moved_timeline = timeline.model_copy(
        update={
            "work_dir": "/another/work",
            "lut_path": "/another/lut",
            "produce_ids": {"master": "another-random-id"},
            "clips": [timeline.clips[0].model_copy(update={"path": "/another/plate"})],
        }
    )
    assert source_key(moved_payload, digest, moved_timeline, config) == original
    assert source_key(payload, digest, timeline, {**config, "long_edge": 320}) != original
    assert source_key(payload, "f" * 64, timeline, config) != original
    default_clock = payload.model_copy(
        update={"target_duration_s": 15, "intro_s": 0, "outro_s": None}
    )
    resolved_clock = default_clock.model_copy(update={"outro_s": 2.4})
    assert source_key(default_clock, digest, timeline, config) == source_key(
        resolved_clock, digest, timeline, config
    )
    first_variant = payload.script.model_copy(update={"script_id": "variant-a"})
    second_variant = payload.script.model_copy(update={"script_id": "variant-b"})
    # The node consumes the last script for each language. Canonical sorting
    # must not merge two different winners into one export directory.
    first_wins = payload.model_copy(update={"variants": [second_variant, first_variant]})
    second_wins = payload.model_copy(update={"variants": [first_variant, second_variant]})
    assert source_key(first_wins, digest, timeline, config) != source_key(
        second_wins, digest, timeline, config
    )


def test_pinned_source_is_an_independent_verified_copy(tmp_path):
    original = tmp_path / "original.mp4"
    original.write_bytes(b"original authorized local fixture bytes")
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    work = tmp_path / "private"
    work.mkdir()
    pinned = pin_source(original, work, digest)
    original.write_bytes(b"a later source revision")
    assert file_hash(pinned) == digest
    assert pinned.read_bytes() != original.read_bytes()
    assert pin_source(original, work, digest) == pinned
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(QAError, match="changed"):
        pin_source(original, other, digest)


def _color(path: Path) -> bytes:
    return subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.05",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout
