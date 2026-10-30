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
        )
    assert second["quality_pass"] is False
    restore_version(project_id, first)
    assert (media / "S01.bin").read_bytes() == b"shot-a"
    assert (directory / "playback" / "master.mp4").read_bytes() == b"master-1"
    restore_version(project_id, second["version_id"])
    assert (media / "S01.bin").read_bytes() == b"shot-a2"
    again = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    assert again["quality_pass"] is False


def test_rollback_after_regenerations_leaves_the_count_unchanged(tmp_path, monkeypatch) -> None:
    from workers.qa.budget_store import open_project_budget

    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    project_id = "regencap"
    init_project(project_id, sentence="一句", status="completed")
    directory = project_path(project_id)
    (directory / "media").mkdir()
    (directory / "media" / "S01.bin").write_bytes(b"a")
    (directory / "project.json").write_text(
        json.dumps({"project_id": project_id, "status": "completed", "regen_used": 0}) + "\n",
        encoding="utf-8",
    )
    listed = list_versions(project_id)
    first = listed["current_version_id"]
    budget = open_project_budget(project_id)
    for _ in range(4):
        assert budget.try_take() is True
    assert open_project_budget(project_id).used == 4
    decoy = directory / "versions" / first / "regen_budget.json"
    decoy.write_text(json.dumps({"used": 0, "limit": 12}) + "\n", encoding="utf-8")
    (directory / "media" / "S01.bin").write_bytes(b"b")
    with locked_project(project_id) as folder:
        snapshot = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        snapshot["regen_used"] = 1
        second = commit_locked(
            folder,
            snapshot,
            instruction="重生",
            quality_pass=False,
            concept_degraded=False,
            executed=["n10_video"],
            video_shots=["S01"],
            decisions=[],
            shot_reviews=[{"shot_id": "S01", "visual_reviewed": False, "quality_pass": False}],
            regen_used=1,
        )
    first_manifest = json.loads(
        (directory / "versions" / first / "manifest.json").read_text(encoding="utf-8")
    )
    second_path = directory / "versions" / second["version_id"] / "manifest.json"
    second_manifest = json.loads(second_path.read_text(encoding="utf-8"))
    assert "regen_used" not in first_manifest
    assert "regen_used" not in second_manifest
    restore_version(project_id, first)
    restored = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    assert "regen_used" not in restored
    assert open_project_budget(project_id).used == 4
    restore_version(project_id, second["version_id"])
    again = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    assert "regen_used" not in again
    assert open_project_budget(project_id).used == 4
    assert json.loads(decoy.read_text(encoding="utf-8"))["used"] == 0


def test_interrupted_restore_puts_the_previous_tree_back(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    project_id = "vercrash"
    init_project(project_id, sentence="一句", status="completed")
    directory = project_path(project_id)
    media = directory / "media"
    media.mkdir()
    (media / "S01.bin").write_bytes(b"live")
    master = directory / "playback" / "master.mp4"
    master.parent.mkdir()
    master.write_bytes(b"live-master")
    update_snapshot(project_id, status="completed", deliverable=str(master))
    listed = list_versions(project_id)
    first = listed["current_version_id"]
    (media / "S01.bin").write_bytes(b"newer")
    master.write_bytes(b"newer-master")
    with locked_project(project_id) as folder:
        snapshot = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        snapshot["deliverable"] = str(master)
        commit_locked(
            folder,
            snapshot,
            instruction="改过",
            quality_pass=False,
            concept_degraded=False,
            executed=[],
            video_shots=[],
            decisions=[],
            shot_reviews=[],
        )
    real_unlink = os.unlink

    def crash_on_marker(path: str, *, dir_fd: int | None = None) -> None:
        if str(path).endswith(".restore-inflight"):
            raise RuntimeError("crash before the restore is published")
        if dir_fd is None:
            real_unlink(path)
        else:
            real_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", crash_on_marker)
    try:
        restore_version(project_id, first)
    except RuntimeError as exc:
        assert "crash" in str(exc)
    else:
        raise AssertionError("restore finished without the injected crash")
    monkeypatch.setattr(os, "unlink", real_unlink)
    list_versions(project_id)
    assert (media / "S01.bin").read_bytes() == b"newer"
    assert master.read_bytes() == b"newer-master"
    body = json.loads((directory / "project.json").read_text(encoding="utf-8"))
    assert "regen_used" not in body
    assert body.get("current_version_id") != first
    assert not (directory / ".restore-inflight").exists()


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
