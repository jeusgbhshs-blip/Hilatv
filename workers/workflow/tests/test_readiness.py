"""Delivery contracts use actual local MP4 bytes and simulated verifier records.

No real speech/VLM accuracy is claimed by the simulated final-review fixture.
"""

import copy
import hashlib
import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from gateway.store import SqlStore
from workers.compliance.metadata import metadata_args
from workers.media.ffmpeg import run_ffmpeg
from workers.media.raster import render_overlay, save_png
from workers.workflow import readiness as gates
from workers.workflow.store import (
    init_project,
    locked_project,
    project_path,
    read_snapshot,
    record_human_release,
    save_node,
    update_snapshot,
)
from workers.workflow.versions import commit_locked, list_versions, restore_version

OWNER = "00000000-0000-0000-0000-000000000001"
SOURCE_HASH = hashlib.sha256(b"original authorized fixture logo").hexdigest()


@pytest.fixture(scope="module")
def film_bytes(tmp_path_factory):
    root = tmp_path_factory.mktemp("readiness-film")
    mark = render_overlay("AI生成", weight="bold", font_size=24, fill="#FFFFFF")
    save_png(mark, root / "label.png")
    logo = Image.new("RGBA", (50, 30))
    ImageDraw.Draw(logo).rectangle((5, 5, 40, 25), fill=(235, 31, 89, 255))
    save_png(logo, root / "logo.png")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HILATV_LIVE", "0")
        patch.setenv("HILATV_AIGC_HMAC_KEY", "pytest-only-fixture-signing-key")
        patch.setenv("HILATV_CONTENT_PRODUCER", "pytest-fixture-provider")
        run_ffmpeg(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x102030:s=320x180:r=30:d=0.4",
                "-f",
                "lavfi",
                "-i",
                "sine=f=330:r=48000:d=0.4",
                "-i",
                str(root / "label.png"),
                "-i",
                str(root / "logo.png"),
                "-filter_complex",
                "[0:v][2:v]overlay=8:8[v1];[v1][3:v]overlay=250:120[v]",
                "-map",
                "[v]",
                "-map",
                "1:a",
                "-t",
                "0.4",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                *metadata_args(content_id="readiness-fixture"),
                str(root / "master.mp4"),
            ]
        )
    return (root / "master.mp4").read_bytes()


@pytest.fixture
def prepared(tmp_path, monkeypatch, film_bytes):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_AIGC_HMAC_KEY", "pytest-only-fixture-signing-key")
    monkeypatch.setenv("HILATV_CONTENT_PRODUCER", "pytest-fixture-provider")
    gates.invalidate_media_cache()
    snapshot = init_project("ready-film", enterprise_id=OWNER, status="completed")
    path = project_path("ready-film") / "renders" / "first.mp4"
    path.parent.mkdir()
    path.write_bytes(film_bytes)
    digest = hashlib.sha256(film_bytes).hexdigest()
    snapshot = update_snapshot("ready-film", deliverable=str(path))
    state = {
        "script": {"shots": [{"shot_id": "S01"}]},
        "brief": {},
        "brand_kit": {},
        "media_provenance": "live",
        "audio_provenance": "live",
        "logo_status": "ready",
        "elements": [{"kind": "outro_logo", "spec": {"source_sha256": SOURCE_HASH}}],
        "licensing_summary": {"records": []},
        "videos": [
            {
                "candidate_id": "v1",
                "shot_id": "S01",
                "node": "N10",
                "selected": True,
                "model": "real-fixture",
                "uri": path.as_uri(),
                "params": {
                    "mock": False,
                    "execution_mode": "live",
                    "generation_source_uri": path.as_uri(),
                },
            }
        ],
    }
    ledger = SqlStore.sqlite(":memory:")
    ledger.conn.execute("""CREATE TABLE IF NOT EXISTS budget_reservations (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, day TEXT NOT NULL,
        amount_cny TEXT NOT NULL, state TEXT NOT NULL, context TEXT NOT NULL)""")
    references = []
    for task, node, output in (
        ("video", "n10_video", {"uri": path.as_uri(), "mock": False}),
        ("judge", "n16_final_review", {"evaluator": "real-fixture"}),
        ("asr", "n16_final_review", {"mock": False, "text": ""}),
        ("content_safety", "n16_review", {"mock": False, "allowed": True}),
    ):
        log_id = str(uuid4())
        ledger.insert_log(
            {
                "id": log_id,
                "created_at": "2026-11-01T00:00:00+00:00",
                "day": "2026-11-01",
                "project_id": "ready-film",
                "node": node,
                "shot_id": "S01" if task == "video" else None,
                "task": task,
                "provider": "real-fixture",
                "model": "real-fixture",
                "params": {"media_hash": digest} if task != "video" else {},
                "latency_ms": 1,
                "cost_cny": "0.0100",
                "status": "ok",
                "live": True,
                "output": output,
            }
        )
        ledger.conn.execute(
            "INSERT INTO budget_reservations VALUES (?, ?, ?, ?, ?, ?)",
            (
                log_id,
                "2026-11-01",
                "2026-11-01",
                "0.0200",
                "settled",
                json.dumps({"project_id": "ready-film"}),
            ),
        )
        references.append(
            {
                "execution_mode": "live",
                "evidence_ref": f"gateway:{log_id}",
                "gateway_log_id": log_id,
                "output_uri": output.get("uri"),
                "billing_status": "settled",
            }
        )
    ledger.conn.commit()
    monkeypatch.setattr(gates, "_source_store", lambda: ledger)
    save_node("ready-film", "n15_compose", state)
    digest = hashlib.sha256(film_bytes).hexdigest()
    review = {
        "media_hash": digest,
        "enterprise_id": OWNER,
        "live": True,
        "release": True,
        "visual_reviewed": True,
        "disposition": "release",
        "issues": [],
        "decisions": [],
        "qa": {
            "scores": {
                name: 8
                for name in (
                    "product_fidelity",
                    "motion_quality",
                    "aesthetics",
                    "prompt_match",
                    "artifact_free",
                )
            },
            "hard_fail": [],
            "total": 8.0,
            "evaluator": "vlm-judge-v1",
            "notes": "quality_pass=true",
            "visual_reviewed": True,
        },
        "asr": {"mock": False, "verified": True, "heard_audio": True, "failed": False},
        "brand": {"complete": True, "ai_label": True, "logo_pixels": True, "cta_pixels": True},
        "compliance": {"passed": True},
        "narrative": {"ok": True},
        "hook": {"ok": True},
        "film_judge": {"usable": True},
        "shots": [{"shot_id": "S01", "visual_reviewed": True, "total": 8.0, "hard_fail": []}],
    }
    proofs = {
        "media_provenance": "live",
        "source_evidence": {
            "media_hash": digest,
            "verified": True,
            "complete": True,
            "records": references,
        },
        "state": state,
        "logo_evidence": {
            "status": "ready",
            "pixels_verified": True,
            "source_sha256": SOURCE_HASH,
            "media_hash": digest,
        },
        "ai_label_evidence": {
            "media_hash": digest,
            "visual_verified": True,
            "metadata_verified": True,
            "visual_method": "pixel_match",
        },
        "authorization_evidence": {
            "passed": True,
            "enterprise_id": OWNER,
            "media_hash": digest,
            "consent_verified": True,
            "evidence_refs": ["server-fixture-proof"],
            "records": [
                {
                    "record_id": "font",
                    "kind": "font",
                    "source": "Noto CJK",
                    "license": "OFL",
                    "evidence_ref": "docs/licenses.md",
                    "expires_on": "none",
                    "usage_scope": "commercial film",
                }
            ],
        },
    }
    yield snapshot, state, path, review, proofs
    ledger.close()


def attest(prepared):
    snapshot, state, path, review, proofs = prepared
    gates.record_render_context(
        snapshot["project_id"],
        path,
        state,
        applied_draft_context=gates.draft_context(snapshot["project_id"]),
    )
    return gates.record_delivery_evidence(snapshot["project_id"], path, review, **proofs)


def codes(view):
    return {reason["code"] for reason in view["reasons"]}


def test_completed_and_client_flags_never_replace_the_server_evidence(prepared):
    snapshot, state, path, review, _proofs = prepared
    spoofed = {
        **snapshot,
        "quality_pass": True,
        "delivery_status": "ready",
        "final_review": review,
        "human_release": True,
    }
    result = gates.readiness(spoofed, {**state, "final_review": review}, path)
    assert result["preview_available"] is True
    assert result["delivery_status"] == "needs_verification"
    assert result["quality_pass"] is False
    assert "final_review_missing" in codes(result)


def test_exact_trusted_evidence_can_release_only_the_matching_media(prepared):
    attest(prepared)
    snapshot, state, path, _review, _proofs = prepared
    result = gates.readiness(snapshot, state, path)
    assert result["quality_pass"] is True
    assert result["delivery_status"] == "ready"
    assert result["reasons"] == []
    changed = copy.deepcopy(state)
    changed["script"]["shots"][0]["voiceover"] = "a changed line"
    assert "review_context_changed" in codes(gates.readiness(snapshot, changed, path))
    path.write_bytes(path.read_bytes() + b"changed trailer")
    assert gates.readiness(snapshot, state, path)["quality_pass"] is False


@pytest.mark.parametrize("provenance", ["mock", "mixed", "unknown"])
def test_non_real_sources_remain_preview_even_after_a_review(prepared, provenance):
    snapshot, state, path, _review, proofs = prepared
    state["audio_provenance"] = provenance
    proofs["media_provenance"] = provenance
    attest(prepared)
    result = gates.readiness(snapshot, state, path)
    assert result["preview_available"] is True
    assert result["quality_pass"] is False
    assert "media_not_live" in codes(result)


@pytest.mark.parametrize(
    "fault,code",
    [
        ("review_hash", "review_media_hash_mismatch"),
        ("review_mock", "final_review_failed"),
        ("score", "final_review_failed"),
        ("hard_flaw", "final_review_failed"),
        ("asr", "audio_review_unverified"),
        ("shot", "shot_review_incomplete"),
        ("label", "ai_label_unverified"),
        ("logo", "logo_unverified"),
        ("rights", "authorization_unverified"),
        ("expired", "license_incomplete"),
        ("safety", "compliance_unverified"),
        ("lineage", "source_lineage_unverified"),
        ("fee", "source_lineage_unverified"),
    ],
)
def test_each_required_evidence_is_fail_closed(prepared, fault, code):
    snapshot, state, path, review, proofs = prepared
    if fault == "review_hash":
        review["media_hash"] = "0" * 64
    elif fault == "review_mock":
        review["live"] = False
    elif fault == "score":
        review["qa"]["total"] = 7.49
    elif fault == "hard_flaw":
        review["qa"]["hard_fail"] = ["face_collapse"]
    elif fault == "asr":
        review["asr"]["mock"] = True
    elif fault == "shot":
        review["shots"] = []
    elif fault == "label":
        proofs["ai_label_evidence"]["visual_verified"] = False
    elif fault == "logo":
        proofs["logo_evidence"]["source_sha256"] = "0" * 64
    elif fault == "rights":
        proofs["authorization_evidence"]["evidence_refs"] = []
    elif fault == "expired":
        proofs["authorization_evidence"]["records"][0]["expires_on"] = "2000-01-01"
    elif fault == "safety":
        review["compliance"]["blocked"] = True
    elif fault == "lineage":
        proofs["source_evidence"]["complete"] = False
    elif fault == "fee":
        proofs["source_evidence"]["records"][0]["billing_status"] = "unknown"
    attest(prepared)
    result = gates.readiness(snapshot, state, path)
    assert not result["quality_pass"]
    assert code in codes(result)


def test_actual_metadata_is_read_instead_of_accepting_the_passed_flag(prepared, monkeypatch):
    snapshot, state, path, _review, _proofs = prepared
    monkeypatch.setenv("HILATV_AIGC_HMAC_KEY", "a-different-pytest-key")
    attest(prepared)
    result = gates.readiness(snapshot, state, path)
    assert "ai_label_unverified" in codes(result)


def test_media_cache_is_scoped_and_invalidated_by_content_changes(prepared, monkeypatch):
    snapshot, state, path, _review, _proofs = prepared
    real_run = gates.subprocess.run
    calls = []

    def spy(*args, **kwargs):
        calls.append(args[0][0])
        return real_run(*args, **kwargs)

    gates.invalidate_media_cache()
    monkeypatch.setattr(gates.subprocess, "run", spy)
    assert gates.readiness(snapshot, state, path)["preview_available"]
    initial = len(calls)
    assert initial == 2
    for _ in range(5):
        assert gates.readiness(snapshot, state, path)["preview_available"]
    assert len(calls) == initial
    old = path.stat()
    path.write_bytes(b"not a playable movie" + b"x" * (old.st_size - 20))
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert not gates.readiness(snapshot, state, path)["preview_available"]
    assert len(calls) > initial
    other = init_project("other-project", enterprise_id=OWNER)
    assert not gates.readiness(other, state, path)["preview_available"]


def test_human_release_does_not_manufacture_final_review(prepared):
    snapshot, state, path, _review, _proofs = prepared
    update_snapshot(
        snapshot["project_id"],
        status="needs_human_review",
        deliverable=None,
        held_deliverable=str(path),
        quality_pass=True,
    )
    record_human_release(snapshot["project_id"], releaser="owner", enterprise_id=OWNER)
    latest = read_snapshot(snapshot["project_id"])
    assert latest["status"] == "completed"
    assert latest["quality_pass"] is False
    assert gates.readiness(latest, state, path)["quality_pass"] is False


def test_human_release_requires_new_evidence_even_if_an_old_review_existed(prepared):
    snapshot, state, path, _review, _proofs = prepared
    attest(prepared)
    update_snapshot(
        snapshot["project_id"],
        status="needs_human_review",
        deliverable=None,
        held_deliverable=str(path),
    )
    record_human_release(snapshot["project_id"], releaser="owner", enterprise_id=OWNER)
    latest = read_snapshot(snapshot["project_id"])
    assert "review_required_after_release" in codes(gates.readiness(latest, state, path))
    attest(prepared)  # A simulated rerun of the independent verifiers, not the release action.
    assert gates.readiness(read_snapshot(snapshot["project_id"]), state, path)["quality_pass"]


def test_version_history_retains_last_ready_while_new_preview_is_unverified(prepared):
    snapshot, state, path, _review, _proofs = prepared
    attest(prepared)
    with locked_project(snapshot["project_id"]) as root:
        first = commit_locked(root, snapshot, instruction="approved", concept_degraded=False)
    assert first["quality_pass"]
    changed = path.with_name("second.mp4")
    changed.write_bytes(path.read_bytes() + b"new-render")
    new_snapshot = update_snapshot(snapshot["project_id"], deliverable=str(changed))
    with locked_project(snapshot["project_id"]) as root:
        second = commit_locked(
            root, new_snapshot, instruction="new preview", concept_degraded=False
        )
    assert not second["quality_pass"]
    view = list_versions(snapshot["project_id"])
    assert view["last_ready_version_id"] == first["version_id"]
    restore_version(snapshot["project_id"], first["version_id"])
    restored = read_snapshot(snapshot["project_id"])
    assert restored["quality_pass"] is True
    assert gates.readiness(restored)["quality_pass"] is True
    version_file = (
        project_path(snapshot["project_id"]) / "versions" / second["version_id"] / "master.mp4"
    )
    assert version_file.is_file()


def test_evidence_copied_from_another_project_never_releases(prepared):
    snapshot, state, path, _review, _proofs = prepared
    attest(prepared)
    other = init_project("foreign-project", enterprise_id=OWNER, status="completed")
    other_path = project_path("foreign-project") / "master.mp4"
    shutil.copy2(path, other_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    foreign = other_path.parent / "reviews" / f"{digest}.json"
    foreign.parent.mkdir()
    shutil.copy2(project_path(snapshot["project_id"]) / "reviews" / f"{digest}.json", foreign)
    assert "media_hash_mismatch" in codes(gates.readiness(other, state, other_path))


def test_failed_render_uses_a_new_folder_and_keeps_the_previous_file(prepared, monkeypatch):
    from temporalio.exceptions import ApplicationError

    from workers.nodes.n15_compose import node
    from workers.nodes.n15_compose.qa import QAError
    from workers.workflow import activities

    snapshot, state, path, _review, _proofs = prepared
    previous = path.read_bytes()
    seen = []

    def fail(raw, **_kwargs):
        work = Path(raw["payload"]["work_dir"])
        seen.append(work)
        work.mkdir(parents=True)
        (work / "master.mp4").write_bytes(b"failed new attempt")
        raise QAError("render failed", retryable=False)

    monkeypatch.setattr(node, "run", fail)
    monkeypatch.setattr(activities, "_announce", lambda *_args: 1)
    request = {
        "project_id": snapshot["project_id"],
        "state": state,
        "request": {"work_dir": str(project_path(snapshot["project_id"]))},
    }
    for _ in range(2):
        with pytest.raises(ApplicationError, match="render failed"):
            activities.n15_compose(request)
    assert seen[0] != seen[1]
    assert path.read_bytes() == previous
    assert read_snapshot(snapshot["project_id"])["deliverable"] == str(path)


def test_corrupt_version_restore_does_not_replace_the_active_file(prepared):
    snapshot, _state, path, _review, _proofs = prepared
    attest(prepared)
    with locked_project(snapshot["project_id"]) as root:
        first = commit_locked(root, snapshot, instruction="approved", concept_degraded=False)
    stored = project_path(snapshot["project_id"]) / "versions" / first["version_id"] / "master.mp4"
    stored.write_bytes(b"a corrupted archived copy")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="校验值"):
        restore_version(snapshot["project_id"], first["version_id"])
    assert path.read_bytes() == before


def test_rerun_keeps_the_previous_preview_without_marking_it_newly_approved(prepared):
    from workers.workflow.service import prepare

    snapshot, state, path, _review, _proofs = prepared
    prepare(
        project_id=snapshot["project_id"],
        sentence="edit",
        start_from="n15_compose",
        checkpoint=state,
    )
    latest = read_snapshot(snapshot["project_id"])
    assert latest["deliverable"] is None
    assert latest["preview_path"] == str(path)
    assert latest["previous_deliverable"] == str(path)
    assert latest["quality_pass"] is False
    assert path.is_file()


def test_an_attested_document_cannot_override_the_current_voice_archive(prepared):
    snapshot, state, path, _review, proofs = prepared
    state["voiceovers"] = [
        {"voice": "unarchived-clone", "provenance": "live", "uri": path.as_uri()}
    ]
    voice = dict(proofs["authorization_evidence"]["records"][0])
    voice.update(record_id="voice", kind="voice")
    proofs["authorization_evidence"]["records"].append(voice)
    attest(prepared)
    assert "consent_unverified" in codes(gates.readiness(snapshot, state, path))


def test_composition_completion_publishes_a_preview_with_independent_readiness(
    prepared, monkeypatch
):
    from types import SimpleNamespace

    from workers.nodes.n15_compose import node
    from workers.workflow import activities

    snapshot, state, previous, _review, _proofs = prepared
    update_snapshot(snapshot["project_id"], revision_incomplete=True)

    def rendered(raw, **_kwargs):
        folder = Path(raw["payload"]["work_dir"])
        folder.mkdir(parents=True)
        target = folder / "master.mp4"
        target.write_bytes(previous.read_bytes())
        return SimpleNamespace(
            payload={
                "exports": {"master": str(target)},
                "audio_provenance": "mock",
                "logo_status": "ready",
                "timeline": {"clips": [{"placeholder": True}]},
            }
        )

    monkeypatch.setattr(node, "run", rendered)
    monkeypatch.setattr(activities, "_announce", lambda *_args: 1)
    activities.n15_compose(
        {
            "project_id": snapshot["project_id"],
            "state": state,
            "request": {"work_dir": str(project_path(snapshot["project_id"]))},
        }
    )
    latest = read_snapshot(snapshot["project_id"])
    assert latest["status"] == "completed"
    assert latest["preview_available"] is True
    assert latest["delivery_status"] == "preview"
    assert latest["quality_pass"] is False
    assert latest["previous_deliverable"] == str(previous)
    assert latest["revision_incomplete"] is False
    assert Path(latest["preview_path"]) != previous
    assert previous.is_file()


@pytest.mark.parametrize("edit", ["narration", "timeline", "reference", "node_prompt"])
def test_saved_edits_invalidate_draft_but_not_an_immutable_version(prepared, edit):
    snapshot, state, path, _review, _proofs = prepared
    attest(prepared)
    with locked_project(snapshot["project_id"]) as root:
        first = commit_locked(root, snapshot, instruction="approved", concept_degraded=False)
    doc = {"positions": {"shot:S01": {"x": 500, "y": 20}}, "layout_version": 10}
    if edit == "narration":
        doc["shots"] = {"S01": {"narration": "a new line"}}
    elif edit == "timeline":
        doc["timeline_clips"] = [
            {"shot_id": "S01", "candidate_id": "other", "in_s": 0.1, "out_s": 0.3}
        ]
    elif edit == "reference":
        doc["shots"] = {"S01": {"reference_upload_id": "a-new-reference"}}
    else:
        doc["user_nodes"] = [
            {
                "id": "u1",
                "kind": "image",
                "position": {"x": 0, "y": 0},
                "data": {"prompt": "new image"},
            }
        ]
        doc["edges"] = [{"source": "u1", "target": "shot:S01", "role": "reference"}]
    canvas = project_path(snapshot["project_id"]) / "canvas.json"
    canvas.write_text(json.dumps(doc))
    assert "review_context_changed" in codes(gates.readiness(snapshot, state, path))
    assert list_versions(snapshot["project_id"])["versions"][0]["quality_pass"] is True
    restore_version(snapshot["project_id"], first["version_id"])
    assert gates.readiness(read_snapshot(snapshot["project_id"]))["quality_pass"] is True
    assert json.loads(canvas.read_text()) == {}


def test_layout_and_unused_candidate_changes_do_not_discard_a_review(prepared):
    snapshot, state, path, _review, _proofs = prepared
    canvas = project_path(snapshot["project_id"]) / "canvas.json"
    doc = {
        "user_nodes": [
            {"id": "u1", "kind": "image", "position": {"x": 0, "y": 0}, "data": {"prompt": "same"}}
        ]
    }
    canvas.write_text(json.dumps(doc))
    attest(prepared)
    doc["user_nodes"][0]["position"] = {"x": 1000, "y": -500}
    doc.update(
        layout_version=20,
        viewport={"x": 120, "y": 160, "zoom": 0.5},
        positions={"final": {"x": 1, "y": 1}},
    )
    doc["shots"] = {"S01": {"regen_count": 8}}
    canvas.write_text(json.dumps(doc))
    state["videos"].append({"candidate_id": "unused", "selected": False, "params": {"mock": True}})
    assert gates.readiness(snapshot, state, path)["quality_pass"] is True
    state["videos"][-1]["selected"] = True
    assert gates.readiness(snapshot, state, path)["quality_pass"] is False


def test_restore_cannot_roll_back_current_license_expiry_or_call_settlement(prepared, monkeypatch):
    from datetime import date

    snapshot, _state, path, _review, proofs = prepared
    proofs["authorization_evidence"]["records"][0]["expires_on"] = "2050-01-01"
    attest(prepared)
    with locked_project(snapshot["project_id"]) as root:
        first = commit_locked(root, snapshot, instruction="approved", concept_degraded=False)
    assert first["quality_pass"]
    monkeypatch.setattr(gates, "today_shanghai", lambda: date(2100, 1, 1))
    restore_version(snapshot["project_id"], first["version_id"])
    assert not read_snapshot(snapshot["project_id"])["quality_pass"]
    assert not list_versions(snapshot["project_id"])["versions"][0]["quality_pass"]
    monkeypatch.setattr(gates, "today_shanghai", lambda: date(2026, 1, 1))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    record_path = project_path(snapshot["project_id"]) / "reviews" / f"{digest}.json"
    record = json.loads(record_path.read_text())
    record["sources"]["records"][0]["billing_status"] = "uncertain"
    record_path.write_text(json.dumps(record))
    restore_version(snapshot["project_id"], first["version_id"])
    assert not read_snapshot(snapshot["project_id"])["quality_pass"]
    assert "source_lineage_unverified" in codes(
        gates.readiness(read_snapshot(snapshot["project_id"]))
    )


def test_restore_does_not_restore_an_old_owner_or_portrait_consent(prepared, monkeypatch):
    from types import SimpleNamespace

    snapshot, state, _path, _review, _proofs = prepared
    state["script"]["shots"][0]["subject_refs"] = ["person:actor"]
    save_node(snapshot["project_id"], "n15_compose", state)
    allowed = [SimpleNamespace(person_id="actor", role="actor")]
    monkeypatch.setattr(gates, "archive_people", lambda _enterprise: allowed)
    attest(prepared)
    with locked_project(snapshot["project_id"]) as root:
        first = commit_locked(root, snapshot, instruction="approved", concept_degraded=False)
    assert first["quality_pass"]
    allowed.clear()
    restore_version(snapshot["project_id"], first["version_id"])
    assert not read_snapshot(snapshot["project_id"])["quality_pass"]
    update_snapshot(snapshot["project_id"], enterprise_id="another-current-owner")
    restore_version(snapshot["project_id"], first["version_id"])
    restored = read_snapshot(snapshot["project_id"])
    assert restored["enterprise_id"] == "another-current-owner"
    assert not restored["quality_pass"]


def test_reviewing_an_old_file_cannot_stamp_a_new_unrendered_draft(prepared):
    snapshot, state, path, review, proofs = prepared
    attest(prepared)
    canvas = project_path(snapshot["project_id"]) / "canvas.json"
    canvas.write_text(
        json.dumps(
            {
                "timeline_clips": [
                    {"shot_id": "S01", "candidate_id": "new", "in_s": 0.1, "out_s": 0.2}
                ]
            }
        )
    )
    # The review writer sees the same bytes, but no renderer consumed the new clip edit.
    gates.record_delivery_evidence(snapshot["project_id"], path, review, **proofs)
    result = gates.readiness(snapshot, state, path)
    assert not result["quality_pass"]
    assert "draft_not_rendered" in codes(result)


def test_an_unrendered_review_attempt_does_not_erase_an_approved_version(prepared):
    snapshot, state, path, review, proofs = prepared
    attest(prepared)
    with locked_project(snapshot["project_id"]) as root:
        first = commit_locked(root, snapshot, instruction="approved", concept_degraded=False)
    changed = copy.deepcopy(state)
    changed["videos"] = [
        {
            "candidate_id": "a-new-selection",
            "selected": True,
            "params": {"mock": False, "execution_mode": "live"},
        }
    ]
    gates.record_delivery_evidence(
        snapshot["project_id"], path, review, **{**proofs, "state": changed}
    )
    assert not gates.readiness(snapshot, changed, path)["quality_pass"]
    assert list_versions(snapshot["project_id"])["versions"][0]["quality_pass"]
    assert first["version_id"] == list_versions(snapshot["project_id"])["last_ready_version_id"]
    assert len(list((project_path(snapshot["project_id"]) / "review-attempts").glob("*.json"))) == 1


@pytest.mark.parametrize(
    "fault",
    [
        "missing_log",
        "wrong_project",
        "mock_provider",
        "unknown_output",
        "wrong_uri",
        "reserved",
        "uncertain",
        "overrun",
        "over_bound",
        "negative_cost",
        "nan_cost",
        "reservation_owner",
        "legacy_schema",
        "asr_hash",
        "asr_text",
        "omitted_used_source",
    ],
)
def test_live_and_settled_claims_cannot_override_actual_gateway_receipts(prepared, fault):
    snapshot, state, path, _review, proofs = prepared
    ledger = gates._source_store()
    first = proofs["source_evidence"]["records"][0]
    log_id = first["gateway_log_id"]
    if fault == "missing_log":
        first["gateway_log_id"] = str(uuid4())
    elif fault == "wrong_project":
        ledger.conn.execute("UPDATE call_logs SET project_id='other' WHERE id=?", (log_id,))
    elif fault == "mock_provider":
        ledger.conn.execute("UPDATE call_logs SET provider='mock', live=0 WHERE id=?", (log_id,))
    elif fault == "unknown_output":
        ledger.conn.execute(
            "UPDATE call_logs SET output=? WHERE id=?", (json.dumps({"uri": path.as_uri()}), log_id)
        )
    elif fault == "wrong_uri":
        ledger.conn.execute(
            "UPDATE call_logs SET output=? WHERE id=?",
            (json.dumps({"uri": "oss://other/source", "mock": False}), log_id),
        )
    elif fault in {"reserved", "uncertain", "overrun"}:
        ledger.conn.execute(
            "UPDATE budget_reservations SET state=? WHERE id=?",
            ("settled_overrun" if fault == "overrun" else fault, log_id),
        )
    elif fault in {"over_bound", "negative_cost", "nan_cost"}:
        ledger.conn.execute(
            "UPDATE call_logs SET cost_cny=? WHERE id=?",
            ({"over_bound": "0.0300", "negative_cost": "-0.01", "nan_cost": "NaN"}[fault], log_id),
        )
    elif fault == "reservation_owner":
        ledger.conn.execute(
            "UPDATE budget_reservations SET context=? WHERE id=?",
            (json.dumps({"project_id": "other"}), log_id),
        )
    elif fault == "legacy_schema":
        ledger.conn.execute("DROP TABLE budget_reservations")
    elif fault == "asr_hash":
        ledger.conn.execute(
            "UPDATE call_logs SET params=? WHERE task='asr'",
            (json.dumps({"media_hash": "0" * 64}),),
        )
    elif fault == "asr_text":
        ledger.conn.execute(
            "UPDATE call_logs SET output=? WHERE task='asr'",
            (json.dumps({"text": "a different narration", "mock": False}),),
        )
    elif fault == "omitted_used_source":
        proofs["source_evidence"]["records"] = proofs["source_evidence"]["records"][1:]
    ledger.conn.commit()
    attest(prepared)
    result = gates.readiness(snapshot, state, path)
    assert result["preview_available"]
    assert not result["quality_pass"]
    assert "source_journal_unverified" in codes(result)
    assert result["media_provenance"] == "unknown"


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "no_origin",
        "origin_unsettled",
        "foreign_origin",
        "different_output",
        "nonzero_cache_cost",
        "cache_claims_live_call",
        "origin_not_live",
        "different_origin_model",
        "different_origin_task",
    ],
)
def test_cached_live_outputs_need_a_matching_settled_origin(prepared, fault):
    snapshot, state, path, _review, proofs = prepared
    ledger = gates._source_store()
    reference = proofs["source_evidence"]["records"][0]
    origin_id = reference["gateway_log_id"]
    original = ledger.fetchall("SELECT * FROM call_logs WHERE id=%s", (origin_id,))[0]
    cache_id = str(uuid4())
    cached = {
        **original,
        "id": cache_id,
        "status": "cache_hit",
        "live": False,
        "cache_hit": True,
        "cost_cny": "0.0000",
        "params": json.loads(original["params"]),
        "output": json.loads(original["output"]),
    }
    ledger.insert_log(cached)
    reference.update(
        gateway_log_id=cache_id, origin_log_id=origin_id, billing_status="not_billable"
    )
    if fault == "no_origin":
        reference.pop("origin_log_id")
    elif fault == "origin_unsettled":
        ledger.conn.execute(
            "UPDATE budget_reservations SET state='uncertain' WHERE id=?", (origin_id,)
        )
    elif fault == "foreign_origin":
        ledger.conn.execute("UPDATE call_logs SET project_id='foreign' WHERE id=?", (origin_id,))
    elif fault == "different_output":
        ledger.conn.execute(
            "UPDATE call_logs SET output=? WHERE id=?",
            (json.dumps({"uri": "oss://other/source", "mock": False}), origin_id),
        )
    elif fault == "nonzero_cache_cost":
        ledger.conn.execute("UPDATE call_logs SET cost_cny='0.01' WHERE id=?", (cache_id,))
    elif fault == "cache_claims_live_call":
        ledger.conn.execute("UPDATE call_logs SET live=1 WHERE id=?", (cache_id,))
    elif fault == "origin_not_live":
        ledger.conn.execute("UPDATE call_logs SET live=0 WHERE id=?", (origin_id,))
    elif fault == "different_origin_model":
        ledger.conn.execute("UPDATE call_logs SET model='another-model' WHERE id=?", (origin_id,))
    elif fault == "different_origin_task":
        ledger.conn.execute("UPDATE call_logs SET task='image' WHERE id=?", (origin_id,))
    ledger.conn.commit()
    attest(prepared)
    result = gates.readiness(snapshot, state, path)
    assert result["quality_pass"] is (fault is None)


@pytest.mark.parametrize("revoke_origin", [False, True])
def test_real_gateway_cache_journal_is_checked_against_its_current_settlement(
    prepared, tmp_path, revoke_origin
):
    from decimal import Decimal

    from gateway.tests.conftest import build_gateway
    from gateway.tests.test_budget import ROUTES, FlatPricing, Priced

    snapshot, state, path, _review, proofs = prepared
    folder = tmp_path / "scripted-gateway"
    folder.mkdir()
    adapter = Priced("0.02")
    gateway = build_gateway(
        folder,
        routes=ROUTES,
        registry={"priced": adapter},
        pricing=FlatPricing("0.02"),
        limits=(True, Decimal("1"), Decimal("1")),
    )
    try:
        kwargs = {"project_id": snapshot["project_id"], "node": "n01_brief", "seed": 17}
        assert gateway.generate_text("original local scripted output", **kwargs) == (
            gateway.generate_text("original local scripted output", **kwargs)
        )
        assert adapter.calls == 1
        origin, cached = gateway.store.list_logs()
        assert origin["status"] == "ok" and origin["live"] == 1
        assert cached["status"] == "cache_hit" and cached["live"] == 0
        ledger = gates._source_store()
        for row in (origin, cached):
            row = dict(row)
            for key in ("params", "output"):
                if isinstance(row[key], str):
                    row[key] = json.loads(row[key])
            ledger.insert_log(row)
        reservation = gateway.store.fetchall(
            "SELECT * FROM budget_reservations WHERE id=%s", (origin["id"],)
        )[0]
        ledger.conn.execute(
            "INSERT INTO budget_reservations VALUES (?, ?, ?, ?, ?, ?)",
            tuple(
                reservation[key]
                for key in ("id", "created_at", "day", "amount_cny", "state", "context")
            ),
        )
        if revoke_origin:
            ledger.conn.execute(
                "UPDATE budget_reservations SET state='uncertain' WHERE id=?", (origin["id"],)
            )
        ledger.conn.commit()
        proofs["source_evidence"]["records"].append(
            {
                "gateway_log_id": cached["id"],
                "origin_log_id": origin["id"],
                "execution_mode": "live",
                "billing_status": "not_billable",
                "evidence_ref": f"gateway:{cached['id']}",
            }
        )
        attest(prepared)
        assert gates.readiness(snapshot, state, path)["quality_pass"] is (not revoke_origin)
    finally:
        gateway.store.close()


def test_actual_cost_revocation_survives_version_restore(prepared):
    snapshot, _state, _path, _review, proofs = prepared
    attest(prepared)
    with locked_project(snapshot["project_id"]) as root:
        approved = commit_locked(root, snapshot, instruction="approved", concept_degraded=False)
    assert approved["quality_pass"]
    ledger = gates._source_store()
    log_id = proofs["source_evidence"]["records"][0]["gateway_log_id"]
    ledger.conn.execute("UPDATE budget_reservations SET state='uncertain' WHERE id=?", (log_id,))
    ledger.conn.commit()
    restore_version(snapshot["project_id"], approved["version_id"])
    assert not read_snapshot(snapshot["project_id"])["quality_pass"]
    assert not list_versions(snapshot["project_id"])["versions"][0]["quality_pass"]
    assert (
        ledger.fetchall("SELECT state FROM budget_reservations WHERE id=%s", (log_id,))[0]["state"]
        == "uncertain"
    )


@pytest.mark.parametrize("claim", ["clips", "reference", "graph"])
def test_render_hook_rejects_a_claim_without_a_real_consumer(prepared, claim):
    snapshot, state, path, _review, _proofs = prepared
    attest(prepared)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    witness = project_path(snapshot["project_id"]) / "render-evidence" / f"{digest}.json"
    before = witness.read_bytes()
    draft = {
        "clips": {"timeline_clips": [{"shot_id": "S01", "in_s": 0.1, "out_s": 0.2}]},
        "reference": {"shots": {"S01": {"reference_upload_id": "new-reference"}}},
        "graph": {"user_nodes": [{"id": "u", "kind": "image", "data": {"prompt": "different"}}]},
    }[claim]
    with pytest.raises(ValueError, match="consumer"):
        gates.record_render_context(
            snapshot["project_id"], path, state, applied_draft_context=draft
        )
    assert witness.read_bytes() == before


def test_a_connected_draft_is_pending_but_an_unconnected_idea_is_not_the_execution_graph(prepared):
    snapshot, state, path, _review, _proofs = prepared
    attest(prepared)
    doc = {"user_nodes": [{"id": "idea", "kind": "image", "data": {"prompt": "an unused idea"}}]}
    canvas = project_path(snapshot["project_id"]) / "canvas.json"
    canvas.write_text(json.dumps(doc))
    assert gates.readiness(snapshot, state, path)["quality_pass"]
    doc["edges"] = [{"source": "idea", "target": "shot:S01", "role": "reference"}]
    canvas.write_text(json.dumps(doc))
    assert "draft_not_rendered" in codes(gates.readiness(snapshot, state, path))


def test_media_cache_cannot_authorize_an_outside_symlink_or_project_alias(prepared):
    snapshot, state, path, _review, _proofs = prepared
    attest(prepared)
    assert gates.readiness(snapshot, state, path)["quality_pass"]
    root = project_path(snapshot["project_id"])
    outside = root.parent / "outside.mp4"
    shutil.copy2(path, outside)
    link = root / "escape.mp4"
    link.symlink_to(outside)
    assert not gates.readiness(snapshot, state, link)["preview_available"]
    moved = root.with_name("other-project")
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
    assert not gates.readiness(snapshot, state, path)["preview_available"]


@pytest.mark.parametrize("node_name", ["n09_keyframe", "n09_keyframe_qa"])
def test_keyframe_review_receipts_accept_the_existing_gateway_node_aliases(prepared, node_name):
    snapshot, state, path, _review, proofs = prepared
    ledger = gates._source_store()
    origin = ledger.fetchall("SELECT * FROM call_logs WHERE task='judge'")[0]
    log_id = str(uuid4())
    ledger.insert_log(
        {
            **origin,
            "id": log_id,
            "node": node_name,
            "params": json.loads(origin["params"]),
            "output": json.loads(origin["output"]),
        }
    )
    ledger.conn.execute(
        "INSERT INTO budget_reservations VALUES (?, ?, ?, ?, ?, ?)",
        (
            log_id,
            "2026-11-01",
            "2026-11-01",
            "0.0200",
            "settled",
            json.dumps({"project_id": snapshot["project_id"]}),
        ),
    )
    ledger.conn.commit()
    proofs["source_evidence"]["records"].append(
        {
            "gateway_log_id": log_id,
            "execution_mode": "live",
            "billing_status": "settled",
            "evidence_ref": f"gateway:{log_id}",
        }
    )
    save_node(snapshot["project_id"], "n09_keyframe_qa", {"keyframes": []})
    attest(prepared)
    assert gates.readiness(snapshot, state, path)["quality_pass"]
