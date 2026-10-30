"""Version ids are server-side. History writes are locked and fsynced."""

import json
import os

from workers.workflow.store import init_project, locked_project, project_path, update_snapshot
from workers.workflow.versions import VersionError, commit_locked, list_versions, restore_version


def test_rollback_any_version_and_fsync(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    project_id = "verrollback"
    init_project(project_id, sentence="一句", status="completed")
    directory = project_path(project_id)
    media = directory / "media"
    media.mkdir()
    (media / "S01.bin").write_bytes(b"shot-a")
    (media / "S02.bin").write_bytes(b"shot-b")
    master = directory / "playback" / "master.mp4"
    master.parent.mkdir()
    master.write_bytes(b"master-1")
    update_snapshot(project_id, status="completed", deliverable=str(master))
    calls = {"n": 0}
    real = os.fsync

    def spy(fd: int) -> None:
        calls["n"] += 1
        real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    listed = list_versions(project_id)
    first = listed["current_version_id"]
    assert first and len(first) == 32
    assert calls["n"] > 0
    assert listed["versions"][0]["quality_pass"] is False
    (media / "S01.bin").write_bytes(b"shot-a2")
    master.write_bytes(b"master-2")
    with locked_project(project_id) as folder:
        snapshot = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        snapshot["deliverable"] = str(master)
        second = commit_locked(
            folder,
            snapshot,
            instruction="改亮",
            quality_pass=True,
            concept_degraded=True,
            executed=["n14_packaging"],
            video_shots=[],
            decisions=[],
            shot_reviews=[
                {"shot_id": "S01", "visual_reviewed": True, "quality_pass": True},
            ],
            regen_used=0,
        )
    assert second["quality_pass"] is False
    restore_version(project_id, first)
    assert (media / "S01.bin").read_bytes() == b"shot-a"
    assert (directory / "playback" / "master.mp4").read_bytes() == b"master-1"
    restore_version(project_id, second["version_id"])
    assert (media / "S01.bin").read_bytes() == b"shot-a2"
    again = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    assert again["quality_pass"] is False


def test_client_version_ids_and_paths_are_rejected(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    project_id = "verreject"
    init_project(project_id, sentence="一句", status="completed")
    update_snapshot(project_id, status="completed")
    list_versions(project_id)
    for bad in ("../etc/passwd", "/tmp/master.mp4", "not-a-version", "a" * 31):
        try:
            restore_version(project_id, bad)
        except VersionError as exc:
            assert exc.status == 404
        else:
            raise AssertionError(bad)
