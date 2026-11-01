"""Restore content targets with the exact archived tree, preserving current access/ledger."""

import hashlib
import json
import os

import pytest

from workers.qa.budget_store import open_project_budget
from workers.workflow.store import (
    init_project,
    locked_project,
    project_path,
    read_snapshot,
    save_node,
    update_snapshot,
)
from workers.workflow.versions import VersionError, commit_locked, list_versions, restore_version

AUTO = {"aspect_ratio": None, "duration_s": None}
FIRST = {"aspect_ratio": "9:16", "duration_s": 15}
SECOND = {"aspect_ratio": "21:9", "duration_s": 60}
RESOLVED_FIRST = {**FIRST, "language": "en"}
RESOLVED_SECOND = {**SECOND, "language": "zh"}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "0")
    project_id = "version-settings"
    init_project(
        project_id,
        status="completed",
        enterprise_id="current-enterprise",
        owner_member_id="first-owner",
        generation_settings=FIRST,
        resolved_generation_settings=RESOLVED_FIRST,
    )
    directory = project_path(project_id)
    master = directory / "playback" / "master.mp4"
    master.parent.mkdir()
    master.write_bytes(b"first-master-bytes")
    update_snapshot(project_id, deliverable=str(master))
    save_node(
        project_id,
        "n01_brief",
        {
            "brief": {
                "aspect_ratios": ["9:16"],
                "duration_s": 15,
                "languages": ["en"],
                "generation_settings": FIRST,
            }
        },
    )
    with locked_project(project_id) as folder:
        manifest = commit_locked(folder, read_snapshot(project_id), instruction="first")
    return project_id, directory, master, manifest


def test_archive_and_restore_targets_do_not_restore_access_or_budget(project):
    project_id, directory, master, manifest = project
    assert manifest["generation_settings"] == FIRST
    assert manifest["resolved_generation_settings"] == RESOLVED_FIRST
    assert "owner_member_id" not in manifest and "enterprise_id" not in manifest
    saved_file = directory / "versions" / manifest["version_id"] / "manifest.json"
    saved_file.write_text(
        json.dumps(
            {
                **manifest,
                "owner_member_id": "decoy-owner",
                "enterprise_id": "decoy-enterprise",
                "members": ["decoy-member"],
                "regen_used": 0,
            }
        ),
        encoding="utf-8",
    )
    update_snapshot(
        project_id,
        generation_settings=SECOND,
        resolved_generation_settings=RESOLVED_SECOND,
        owner_member_id="current-owner",
        members=["current-member"],
    )
    ledger = open_project_budget(project_id)
    assert ledger.try_take()
    budget_before = (directory / "regen_budget.json").read_bytes()
    master.write_bytes(b"second-master-bytes")
    result = restore_version(project_id, manifest["version_id"])
    restored = read_snapshot(project_id)
    assert restored["generation_settings"] == FIRST
    assert restored["resolved_generation_settings"] == RESOLVED_FIRST
    assert restored["owner_member_id"] == "current-owner"
    assert restored["enterprise_id"] == "current-enterprise"
    assert restored["members"] == ["current-member"]
    assert (directory / "regen_budget.json").read_bytes() == budget_before
    assert master.read_bytes() == b"first-master-bytes"
    assert result["versions"][0]["generation_settings"] == FIRST
    assert result["versions"][0]["resolved_generation_settings"] == RESOLVED_FIRST


@pytest.mark.parametrize("brief_explicit", [None, FIRST])
def test_legacy_manifest_uses_archived_brief_never_current_snapshot(project, brief_explicit):
    project_id, directory, _master, manifest = project
    folder = directory / "versions" / manifest["version_id"]
    legacy = dict(manifest)
    legacy.pop("generation_settings")
    legacy.pop("resolved_generation_settings")
    (folder / "manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
    brief = {"aspect_ratios": ["9:16"], "duration_s": 15, "languages": ["en"]}
    if brief_explicit is not None:
        brief["generation_settings"] = brief_explicit
    (folder / "nodes/n01_brief.json").write_text(json.dumps({"brief": brief}), encoding="utf-8")
    update_snapshot(
        project_id, generation_settings=SECOND, resolved_generation_settings=RESOLVED_SECOND
    )
    restored = restore_version(project_id, manifest["version_id"])
    snapshot = read_snapshot(project_id)
    assert snapshot["generation_settings"] == (brief_explicit or AUTO)
    assert snapshot["resolved_generation_settings"] == RESOLVED_FIRST
    assert restored["versions"][0]["resolved_generation_settings"] == RESOLVED_FIRST


def test_old_version_with_no_brief_clears_new_target_labels(project):
    project_id, directory, _master, manifest = project
    folder = directory / "versions" / manifest["version_id"]
    legacy = dict(manifest)
    legacy.pop("generation_settings")
    legacy.pop("resolved_generation_settings")
    (folder / "manifest.json").write_text(json.dumps(legacy), encoding="utf-8")
    (folder / "nodes/n01_brief.json").unlink()
    update_snapshot(
        project_id, generation_settings=SECOND, resolved_generation_settings=RESOLVED_SECOND
    )
    restore_version(project_id, manifest["version_id"])
    snapshot = read_snapshot(project_id)
    assert snapshot["generation_settings"] == AUTO
    assert snapshot["resolved_generation_settings"] == {**AUTO, "language": None}


@pytest.mark.parametrize(
    "corruption",
    [
        {"generation_settings": {"duration_s": True}},
        {"resolved_generation_settings": {"duration_s": 181}},
        {"resolved_generation_settings": {"aspect_ratio": "bad"}},
        {"resolved_generation_settings": {"language": "not a language"}},
    ],
)
def test_invalid_archived_intent_does_not_publish_partial_restore(project, corruption):
    project_id, directory, master, manifest = project
    folder = directory / "versions" / manifest["version_id"]
    (folder / "manifest.json").write_text(json.dumps({**manifest, **corruption}), encoding="utf-8")
    update_snapshot(
        project_id, generation_settings=SECOND, resolved_generation_settings=RESOLVED_SECOND
    )
    master.write_bytes(b"current-media")
    before = (directory / "project.json").read_bytes()
    with pytest.raises(VersionError):
        restore_version(project_id, manifest["version_id"])
    assert (directory / "project.json").read_bytes() == before
    assert master.read_bytes() == b"current-media"


def test_crash_recovery_restores_previous_targets_with_previous_media(project, monkeypatch):
    project_id, directory, master, manifest = project
    update_snapshot(
        project_id,
        generation_settings=SECOND,
        resolved_generation_settings=RESOLVED_SECOND,
        owner_member_id="current-owner",
    )
    master.write_bytes(b"current-media")
    original_unlink = os.unlink

    def crash(path, *, dir_fd=None):
        if str(path).endswith(".restore-inflight"):
            raise RuntimeError("synthetic crash before publish")
        return original_unlink(path, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", crash)
    with pytest.raises(RuntimeError, match="synthetic crash"):
        restore_version(project_id, manifest["version_id"])
    monkeypatch.setattr(os, "unlink", original_unlink)
    list_versions(project_id)
    snapshot = read_snapshot(project_id)
    assert snapshot["generation_settings"] == SECOND
    assert snapshot["resolved_generation_settings"] == RESOLVED_SECOND
    assert snapshot["owner_member_id"] == "current-owner"
    assert master.read_bytes() == b"current-media"


def test_original_hash_gate_remains_before_settings_publish(project):
    project_id, directory, master, manifest = project
    folder = directory / "versions" / manifest["version_id"]
    manifest["media_hash"] = hashlib.sha256(b"first-master-bytes").hexdigest()
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "master.mp4").write_bytes(b"tampered-archive")
    update_snapshot(
        project_id, generation_settings=SECOND, resolved_generation_settings=RESOLVED_SECOND
    )
    before = (directory / "project.json").read_bytes()
    with pytest.raises(VersionError, match="校验值"):
        restore_version(project_id, manifest["version_id"])
    assert (directory / "project.json").read_bytes() == before
    assert master.read_bytes() == b"first-master-bytes"
