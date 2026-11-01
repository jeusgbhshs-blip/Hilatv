"""Saved settings survive CAS/ACK loss and are the only source for model requests."""

import copy
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from apps.api.tests.test_concept_drafts import fake_nodes
from apps.api.tests.test_project_drafts import setup as setup

from workers.identity.session import open_session
from workers.schemas.generation import GenerationSettings
from workers.workflow.drafts import _fields_hash
from workers.workflow.film import _public
from workers.workflow.service import make_request, prepare
from workers.workflow.store import (
    init_project,
    project_path,
    read_snapshot,
    save_node,
    update_snapshot,
)

AUTO = {"aspect_ratio": None, "duration_s": None}
CHOSEN = {"aspect_ratio": "21:9", "duration_s": 30}


def create(client, **fields):
    response = client.post(
        "/v1/projects/drafts",
        json={"operation_id": str(uuid.uuid4()), "sentence": "机床抖音15秒宣传", **fields},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_settings_are_part_of_create_identity_and_public_snapshot(setup):
    client, _identity, _temporal = setup
    body = {
        "operation_id": str(uuid.uuid4()),
        "sentence": "机床宣传",
        "generation_settings": CHOSEN,
    }
    original = client.post("/v1/projects/drafts", json=body)
    assert original.status_code == 201
    assert client.post("/v1/projects/drafts", json=copy.deepcopy(body)).json() == original.json()
    conflict = client.post("/v1/projects/drafts", json={**body, "generation_settings": AUTO})
    assert conflict.status_code == 409
    project_id = original.json()["project_id"]
    assert client.get(f"/v1/projects/{project_id}").json()["generation_settings"] == CHOSEN
    assert create(client)["snapshot"]["generation_settings"] == AUTO


def test_setting_cas_conflicts_and_tenant_guards_preserve_saved_choice(setup):
    client, _identity, temporal = setup
    draft = create(client)
    project_id = draft["project_id"]
    path = f"/v1/projects/{project_id}/draft"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda ratio: client.put(
                    path,
                    json={
                        "draft_revision": 1,
                        "sentence": "机床宣传",
                        "generation_settings": {"aspect_ratio": ratio, "duration_s": 30},
                    },
                ),
                ["21:9", "4:3"],
            )
        )
    assert sorted(response.status_code for response in results) == [200, 409]
    saved = read_snapshot(project_id)["generation_settings"]
    foreign = open_session()
    response = client.put(
        path,
        headers={"Authorization": f"Bearer {foreign.token}"},
        json={"draft_revision": 2, "sentence": "不能修改", "generation_settings": AUTO},
    )
    assert response.status_code == 404
    assert read_snapshot(project_id)["generation_settings"] == saved
    assert temporal.calls == []


@pytest.mark.parametrize(
    "settings",
    [
        {"duration_s": True},
        {"duration_s": 15.0},
        {"duration_s": "15"},
        {"duration_s": 4},
        {"duration_s": 181},
        {"aspect_ratio": "2:1"},
        {"aspect_ratio": "16:9", "fps": 30},
    ],
)
def test_invalid_settings_fail_before_any_draft_write(setup, settings):
    client, _identity, temporal = setup
    draft = create(client)
    before = (project_path(draft["project_id"]) / "project.json").read_bytes()
    response = client.put(
        f"/v1/projects/{draft['project_id']}/draft",
        json={"draft_revision": 1, "sentence": "不应修改", "generation_settings": settings},
    )
    assert response.status_code == 422
    assert (project_path(draft["project_id"]) / "project.json").read_bytes() == before
    assert temporal.calls == []


def test_changed_settings_invalidate_scheme_and_lost_ack_recovers_exactly(setup):
    client, identity, _temporal = setup
    draft = create(client)
    project_id = draft["project_id"]
    save_node(
        project_id,
        "n03_concept",
        {"concept": {"degraded": True, "text_source": "template_fallback", "directions": []}},
    )
    update_snapshot(
        project_id,
        concept_preview={"directions": []},
        concept_preview_sentence="机床抖音15秒宣传",
        concept_selection="d2",
    )
    body = {
        "draft_revision": 1,
        "sentence": "机床抖音15秒宣传",
        "generation_settings": CHOSEN,
        "concept_selection": "d2",
    }
    path = f"/v1/projects/{project_id}/draft"
    saved = client.put(path, json=body)
    assert saved.status_code == 200, saved.text
    snapshot = saved.json()["snapshot"]
    assert snapshot["concept_preview"] is None and snapshot["concept_selection"] is None
    assert snapshot["concept_preview_generation_settings"] is None
    assert snapshot["concept_text_source"] == "" and snapshot["concept_ok"] is None
    assert snapshot["owner_member_id"] == identity.member_id
    committed = (project_path(project_id) / "project.json").read_bytes()
    assert client.put(path, json=copy.deepcopy(body)).json() == saved.json()
    assert (project_path(project_id) / "project.json").read_bytes() == committed
    assert client.put(path, json={**body, "generation_settings": AUTO}).status_code == 409
    assert client.put(path, json={**body, "draft_revision": 2}).status_code == 200
    assert client.put(path, json=body).status_code == 409
    assert client.get(f"/v1/projects/{project_id}").json()["concept_selection"] is None


def test_concepts_use_saved_settings_and_freeze_preview_metadata(setup, monkeypatch):
    client, _identity, _temporal = setup
    draft = create(client, generation_settings=CHOSEN)
    captured = []
    fake_nodes(monkeypatch, captured)
    response = client.post(
        "/v1/concepts", json={"project_id": draft["project_id"], "draft_revision": 1}
    )
    assert response.status_code == 200, response.text
    assert captured[0]["payload"]["generation_settings"] == CHOSEN
    assert captured[0]["payload"]["raw_input"] == draft["snapshot"]["sentence"]
    assert response.json()["generation_settings"] == CHOSEN
    snapshot = client.get(f"/v1/projects/{draft['project_id']}").json()
    assert snapshot["concept_preview_generation_settings"] == CHOSEN
    assert snapshot["concept_preview_invalidated"] is False
    # The modern endpoint deliberately has no unsaved settings input.
    assert (
        client.post(
            "/v1/concepts",
            json={
                "project_id": draft["project_id"],
                "draft_revision": 1,
                "generation_settings": AUTO,
            },
        ).status_code
        == 422
    )


def test_settings_saved_during_concepts_discard_outdated_result(setup, monkeypatch):
    client, _identity, _temporal = setup
    draft = create(client)
    project_id = draft["project_id"]

    def save_new_settings():
        response = client.put(
            f"/v1/projects/{project_id}/draft",
            json={
                "draft_revision": 1,
                "sentence": draft["snapshot"]["sentence"],
                "generation_settings": CHOSEN,
            },
        )
        assert response.status_code == 200

    fake_nodes(monkeypatch, [], save_new_settings)
    assert (
        client.post(
            "/v1/concepts", json={"project_id": project_id, "draft_revision": 1}
        ).status_code
        == 409
    )
    assert read_snapshot(project_id)["concept_preview"] is None
    assert not (project_path(project_id) / "nodes/n03_concept.json").exists()


def test_submission_freezes_settings_and_uncertain_retries_do_not_queue_twice(setup):
    client, _identity, temporal = setup
    draft = create(client, generation_settings=CHOSEN)
    temporal.failure = TimeoutError("synthetic lost acknowledgement")
    body = {"operation_id": str(uuid.uuid4()), "draft_revision": 1}
    path = f"/v1/projects/{draft['project_id']}/film/start"
    response = client.post(path, json=body)
    assert response.status_code == 202
    assert temporal.calls[0]["request"]["generation_settings"] == CHOSEN
    assert response.json()["submission_state"] == "unknown_external_result"
    assert client.post(path, json=body).status_code == 202 and len(temporal.calls) == 1
    assert (
        client.put(
            f"/v1/projects/{draft['project_id']}/draft",
            json={"draft_revision": 1, "sentence": "不能修改", "generation_settings": AUTO},
        ).status_code
        == 409
    )
    assert read_snapshot(draft["project_id"])["generation_settings"] == CHOSEN


def test_prepare_preserved_claim_uses_owned_snapshot_settings_not_second_input(setup):
    client, _identity, _temporal = setup
    draft = create(client, generation_settings=CHOSEN)
    project_id = draft["project_id"]
    update_snapshot(project_id, workflow_id="claimed-workflow")
    request, _ = prepare(
        project_id=project_id,
        sentence="机床宣传",
        generation_settings=AUTO,
        workflow_id="claimed-workflow",
        preserve_project=True,
    )
    assert request["generation_settings"] == CHOSEN
    assert _public(request)["generation_settings"] == CHOSEN
    rerun, _ = prepare(project_id=project_id, sentence="旧重跑入口", start_from="n01_brief")
    assert rerun["generation_settings"] == CHOSEN
    assert make_request(project_id=project_id, sentence="旧客户端")["generation_settings"] == AUTO
    assert (
        make_request(
            project_id=project_id,
            sentence="模型合同",
            generation_settings=GenerationSettings(**CHOSEN),
        )["generation_settings"]
        == CHOSEN
    )


def test_legacy_local_draft_create_retry_does_not_lose_project(setup):
    client, identity, _temporal = setup
    draft = create(client)
    project_id = draft["project_id"]
    snapshot = read_snapshot(project_id)
    initial = snapshot["_draft_create"]
    fields = {
        key: snapshot[key]
        for key in (
            "sentence",
            "brand_kit",
            "brand_id",
            "attachments",
            "concept_selection",
            "skip_storyboard",
        )
    }
    snapshot.pop("generation_settings")
    snapshot["_draft_create"] = {**initial, "fingerprint": _fields_hash(fields)}
    init_project(
        project_id, **{key: value for key, value in snapshot.items() if key != "project_id"}
    )
    response = client.post(
        "/v1/projects/drafts",
        json={"operation_id": initial["operation_id"], "sentence": fields["sentence"]},
    )
    assert response.status_code == 200 and response.json()["project_id"] == project_id
    assert response.json()["snapshot"]["generation_settings"] == AUTO
    assert read_snapshot(project_id)["owner_member_id"] == identity.member_id
