"""Durable draft/CAS/single-submit regressions; no Temporal server or model calls."""

from __future__ import annotations

import asyncio
import base64
import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from workers.identity.session import mint_session_for_tests, open_session
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.workflow.store import project_path, read_snapshot, save_node

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeTemporal:
    def __init__(self):
        self.calls = []
        self.exists = False
        self.failure = None
        self.describes = 0

    async def start_workflow(self, _run, request, *, id, task_queue):
        self.calls.append({"request": copy.deepcopy(request), "id": id})
        await asyncio.sleep(0)
        if self.failure:
            raise self.failure
        self.exists = True
        return SimpleNamespace(id=id)

    def get_workflow_handle(self, workflow_id):
        self.describes += 1

        async def describe():
            if not self.exists:
                raise LookupError("workflow is not confirmed")
            return SimpleNamespace(id=workflow_id)

        return SimpleNamespace(describe=describe)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path / "brands"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.setenv("HILATV_DAILY_BUDGET_CNY", "0")
    monkeypatch.setenv("DATABASE_URL", "")
    temporal = FakeTemporal()

    async def runtime():
        return SimpleNamespace(client=temporal)

    monkeypatch.setattr("app.projects.get_runtime", runtime)
    ident = open_session()
    client = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    return client, ident, temporal


def _create(client, **fields):
    return client.post("/v1/projects/drafts", json={"operation_id": str(uuid.uuid4()), **fields})


def _submit(client, project, **fields):
    return client.post(
        f"/v1/projects/{project['project_id']}/film/start",
        json={
            "operation_id": str(uuid.uuid4()),
            "draft_revision": project["draft_revision"],
            **fields,
        },
    )


def test_empty_draft_is_durable_and_create_retry_returns_original(setup):
    client, ident, temporal = setup
    body = {"operation_id": str(uuid.uuid4()), "sentence": ""}
    first = client.post("/v1/projects/drafts", json=body)
    assert first.status_code == 201
    draft = first.json()
    assert draft["draft_id"] == draft["project_id"]
    assert draft["draft_revision"] == 1 and draft["status"] == "draft"
    assert draft["snapshot"]["skip_storyboard"] is False
    assert not any(key.startswith("_") for key in draft["snapshot"])
    restarted_client = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    retried = restarted_client.post("/v1/projects/drafts", json=body)
    assert retried.status_code == 200 and retried.json() == draft
    snapshot = read_snapshot(draft["project_id"])
    assert snapshot["owner_member_id"] == ident.member_id
    assert snapshot["enterprise_id"] == ident.enterprise_id
    assert temporal.calls == []
    assert client.get("/v1/projects").json()["projects"][0]["project_id"] == draft["project_id"]


def test_concurrent_creation_is_one_project_and_changed_create_operation_conflicts(setup):
    client, _, _ = setup
    body = {"operation_id": str(uuid.uuid4()), "sentence": "一份需求"}
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(
            pool.map(lambda _: client.post("/v1/projects/drafts", json=body), range(3))
        )
    assert sorted(item.status_code for item in responses) == [200, 200, 201]
    assert len({item.json()["project_id"] for item in responses}) == 1
    changed = client.post("/v1/projects/drafts", json={**body, "sentence": "另一个需求"})
    assert changed.status_code == 409
    assert changed.json()["detail"]["code"] == "operation_conflict"


def test_same_operation_in_another_tenant_is_a_distinct_draft_and_access_stays_private(setup):
    client, _, temporal = setup
    other = open_session()
    outsider = TestClient(app, headers={"Authorization": f"Bearer {other.token}"})
    body = {"operation_id": str(uuid.uuid4()), "sentence": "本企业需求"}
    draft = client.post("/v1/projects/drafts", json=body).json()
    theirs = outsider.post("/v1/projects/drafts", json=body).json()
    assert draft["project_id"] != theirs["project_id"]
    assert outsider.get(f"/v1/projects/{draft['project_id']}").status_code == 404
    assert (
        outsider.put(
            f"/v1/projects/{draft['project_id']}/draft",
            json={"draft_revision": 1, "sentence": "偷改"},
        ).status_code
        == 404
    )
    assert _submit(outsider, draft).status_code == 404
    assert temporal.calls == []


def test_save_cas_has_exactly_one_winner_and_preserves_owner(setup):
    client, ident, _ = setup
    draft = _create(client, sentence="原稿").json()
    path = f"/v1/projects/{draft['project_id']}/draft"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda text: client.put(path, json={"draft_revision": 1, "sentence": text}),
                ["甲", "乙"],
            )
        )
    assert sorted(item.status_code for item in responses) == [200, 409]
    winner = next(item.json() for item in responses if item.status_code == 200)
    conflict = next(item.json()["detail"] for item in responses if item.status_code == 409)
    assert winner["draft_revision"] == conflict["draft_revision"] == 2
    assert conflict["snapshot"]["sentence"] == winner["snapshot"]["sentence"]
    assert read_snapshot(draft["project_id"])["owner_member_id"] == ident.member_id


def test_saved_draft_with_lost_ack_is_recovered_by_same_normalized_retry(setup):
    client, ident, _ = setup
    draft = _create(client, sentence="原稿").json()
    path = f"/v1/projects/{draft['project_id']}/draft"
    body = {
        "draft_revision": 1,
        "sentence": "  已保存而响应丢失  ",
        "attachments": [{"kind": "url", "uri": "https://example.test/spec"}],
        "skip_storyboard": False,
        "concept_selection": "concept-2",
    }

    def committed_but_ack_lost():
        response = client.put(path, json=body)
        assert response.status_code == 200
        raise ConnectionError("client lost the successful response")

    with pytest.raises(ConnectionError, match="lost"):
        committed_but_ack_lost()
    saved_path = project_path(draft["project_id"]) / "project.json"
    before = saved_path.read_bytes()
    restarted = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    retried = restarted.put(path, json={**body, "sentence": body["sentence"].strip()})
    assert retried.status_code == 200, retried.text
    assert retried.json()["draft_revision"] == 2
    assert retried.json()["snapshot"]["sentence"] == "已保存而响应丢失"
    assert retried.json()["snapshot"]["owner_member_id"] == ident.member_id
    assert not any(key.startswith("_") for key in retried.json()["snapshot"])
    assert saved_path.read_bytes() == before  # ACK recovery is a read, not another revision.


@pytest.mark.parametrize(
    "changes",
    [
        {"sentence": "不能把另一段文字当成丢失响应"},
        {"attachments": [{"kind": "url", "uri": "https://example.test/changed"}]},
        {"skip_storyboard": True},
        {"concept_selection": "concept-3"},
        {"brand_id": "another-brand"},
    ],
)
def test_old_revision_with_different_full_payload_still_conflicts(setup, changes):
    client, _, _ = setup
    draft = _create(client, sentence="原稿").json()
    path = f"/v1/projects/{draft['project_id']}/draft"
    body = {"draft_revision": 1, "sentence": "保存版本", "concept_selection": "concept-2"}
    assert client.put(path, json=body).status_code == 200
    saved_path = project_path(draft["project_id"]) / "project.json"
    before = saved_path.read_bytes()
    conflict = client.put(path, json={**body, **changes})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "draft_conflict"
    assert conflict.json()["detail"]["draft_revision"] == 2
    assert saved_path.read_bytes() == before


def test_ack_recovery_never_jumps_past_a_subsequent_teammate_revision(setup):
    client, ident, _ = setup
    draft = _create(client, sentence="原稿").json()
    path = f"/v1/projects/{draft['project_id']}/draft"
    body = {"draft_revision": 1, "sentence": "保存版本"}
    assert client.put(path, json=body).json()["draft_revision"] == 2
    colleague = mint_session_for_tests(ident.enterprise_id)
    teammate = TestClient(app, headers={"Authorization": f"Bearer {colleague.token}"})
    # Even a subsequent save of identical content is a distinct acknowledged revision.
    assert teammate.put(path, json={**body, "draft_revision": 2}).json()["draft_revision"] == 3
    saved_path = project_path(draft["project_id"]) / "project.json"
    before = saved_path.read_bytes()
    conflict = client.put(path, json=body)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["draft_revision"] == 3
    assert conflict.json()["detail"]["snapshot"]["owner_member_id"] == ident.member_id
    assert saved_path.read_bytes() == before


def test_valid_uploads_persist_publicly_and_foreign_upload_failure_does_not_modify(setup):
    client, _, _ = setup
    attached = client.post("/v1/uploads", files={"file": ("product.png", PNG, "image/png")}).json()
    draft = _create(client, sentence="带图", attachments=[attached]).json()
    public = draft["snapshot"]["attachments"][0]
    assert public["upload_id"] == attached["upload_id"] and "uri" not in public
    path = project_path(draft["project_id"]) / "project.json"
    before = path.read_bytes()
    other = open_session()
    outsider = TestClient(app, headers={"Authorization": f"Bearer {other.token}"})
    foreign = outsider.post("/v1/uploads", files={"file": ("x.png", PNG, "image/png")}).json()
    failed = client.put(
        f"/v1/projects/{draft['project_id']}/draft",
        json={"draft_revision": 1, "attachments": [foreign]},
    )
    assert failed.status_code == 422 and path.read_bytes() == before


@pytest.mark.parametrize(
    "changes",
    [
        {"draft_revision": 0},
        {"draft_revision": True},
        {"enterprise_id": "injected"},
        {"sentence": "x" * 4001},
        {"attachments": [{"kind": "image", "uri": "/etc/passwd"}]},
    ],
)
def test_invalid_save_leaves_file_byte_identical(setup, changes):
    client, _, _ = setup
    draft = _create(client, sentence="原稿").json()
    path = project_path(draft["project_id"]) / "project.json"
    before = path.read_bytes()
    response = client.put(
        f"/v1/projects/{draft['project_id']}/draft", json={"draft_revision": 1, **changes}
    )
    assert response.status_code == 422 and path.read_bytes() == before


def test_start_consumes_saved_fields_once_and_preserves_project_owner(setup):
    client, ident, temporal = setup
    attached = client.post("/v1/uploads", files={"file": ("product.png", PNG, "image/png")}).json()
    draft = _create(client, sentence="原稿").json()
    saved = client.put(
        f"/v1/projects/{draft['project_id']}/draft",
        json={
            "draft_revision": 1,
            "sentence": "已保存需求",
            "attachments": [attached],
            "concept_selection": "concept-2",
            "brand_id": "saved-brand",
            "skip_storyboard": False,
        },
    ).json()
    operation = str(uuid.uuid4())
    started = _submit(client, saved, operation_id=operation)
    assert started.status_code == 202, started.text
    assert started.json()["submission_state"] == "submitted"
    assert started.json()["status"] == "running"
    assert len(temporal.calls) == 1
    request = temporal.calls[0]["request"]
    assert request["project_id"] == draft["project_id"]
    assert request["sentence"] == "已保存需求" and request["concept_selection"] == "concept-2"
    assert request["skip_storyboard"] is False and request["brand_id"] == "saved-brand"
    assert request["attachments"][0]["upload_id"] == attached["upload_id"]
    snapshot = read_snapshot(draft["project_id"])
    assert snapshot["owner_member_id"] == ident.member_id and snapshot["draft_revision"] == 2
    repeated = _submit(client, saved, operation_id=operation)
    assert repeated.json() == started.json() and len(temporal.calls) == 1
    assert _submit(client, saved).status_code == 409
    assert (
        client.put(
            f"/v1/projects/{draft['project_id']}/draft",
            json={"draft_revision": 2, "sentence": "覆盖"},
        ).status_code
        == 409
    )


def test_concurrent_same_submit_enqueues_once_and_different_operation_cannot_bypass(setup):
    client, _, temporal = setup
    draft = _create(client, sentence="只提交一次").json()
    operation = str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(
            pool.map(lambda _: _submit(client, draft, operation_id=operation), range(3))
        )
    assert all(item.status_code == 202 for item in responses)
    assert len({item.json()["workflow_id"] for item in responses}) == 1
    assert len(temporal.calls) == 1
    assert _submit(client, draft).status_code == 409


def test_unavailable_runtime_does_not_modify_saved_draft(setup, monkeypatch):
    client, _, temporal = setup
    draft = _create(client, sentence="需求不丢").json()
    path = project_path(draft["project_id"]) / "project.json"
    before = path.read_bytes()

    async def down():
        raise ConnectionError("offline")

    monkeypatch.setattr("app.projects.get_runtime", down)
    response = _submit(client, draft)
    assert response.status_code == 503 and path.read_bytes() == before and temporal.calls == []


def test_submit_rechecks_revision_after_runtime_connection_without_overwriting_newer_edit(
    setup, monkeypatch
):
    client, ident, temporal = setup
    draft = _create(client, sentence="连接之前").json()

    async def runtime_after_other_tab_saved():
        from workers.workflow.drafts import save_draft

        save_draft(
            draft["project_id"],
            enterprise_id=ident.enterprise_id,
            revision=1,
            fields={"sentence": "另一页面的新内容"},
        )
        return SimpleNamespace(client=temporal)

    monkeypatch.setattr("app.projects.get_runtime", runtime_after_other_tab_saved)
    response = _submit(client, draft)
    assert response.status_code == 409
    snapshot = read_snapshot(draft["project_id"])
    assert snapshot["status"] == "draft" and snapshot["draft_revision"] == 2
    assert snapshot["sentence"] == "另一页面的新内容" and "_submission" not in snapshot
    assert temporal.calls == []


def test_unknown_external_result_is_durable_and_retry_only_queries(setup):
    client, ident, temporal = setup
    draft = _create(client, sentence="响应丢失也不能重提").json()
    temporal.failure = TimeoutError("acknowledgement lost")
    operation = str(uuid.uuid4())
    first = _submit(client, draft, operation_id=operation)
    assert (
        first.status_code == 202 and first.json()["submission_state"] == "unknown_external_result"
    )
    snapshot = client.get(f"/v1/projects/{draft['project_id']}").json()
    assert snapshot["status"] == "submitting" and snapshot["submission_message"]
    assert (
        snapshot["sentence"] == "响应丢失也不能重提"
        and snapshot["owner_member_id"] == ident.member_id
    )
    restarted = TestClient(app, headers={"Authorization": f"Bearer {ident.token}"})
    second = _submit(restarted, draft, operation_id=operation)
    assert second.json()["submission_state"] == "unknown_external_result"
    assert len(temporal.calls) == 1 and temporal.describes == 1
    assert _submit(restarted, draft).status_code == 409
    temporal.exists = True  # Invoice/workflow query confirms the original acceptance.
    reconciled = _submit(restarted, draft, operation_id=operation)
    assert reconciled.json()["submission_state"] == "submitted"
    assert reconciled.json()["workflow_id"] == first.json()["workflow_id"]
    assert len(temporal.calls) == 1


def test_pending_full_submit_cannot_be_bypassed_with_rerun_or_revision(setup, monkeypatch):
    client, _, temporal = setup
    draft = _create(client, sentence="提交待确认").json()
    temporal.failure = TimeoutError("unknown")
    first = _submit(client, draft)
    assert first.json()["submission_state"] == "unknown_external_result"

    def forbidden_gateway():
        raise AssertionError("pending submission must not invoke any revision gateway")

    monkeypatch.setattr("app.projects.get_gateway", forbidden_gateway)
    for endpoint, body in [
        ("rerun", {"node": "n01_brief"}),
        ("revisions", {"instruction": "修改一遍"}),
    ]:
        response = client.post(f"/v1/projects/{draft['project_id']}/{endpoint}", json=body)
        assert (
            response.status_code == 409
            and response.json()["detail"]["code"] == "submission_pending"
        )
    assert len(temporal.calls) == 1


def test_same_submit_operation_cannot_be_rebound_to_a_different_revision(setup):
    client, _, temporal = setup
    draft = _create(client, sentence="提交绑定版本").json()
    operation = str(uuid.uuid4())
    first = _submit(client, draft, operation_id=operation)
    assert first.json()["submission_state"] == "submitted"
    conflict = _submit(client, draft, operation_id=operation, draft_revision=2)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "operation_conflict"
    assert len(temporal.calls) == 1


def test_stale_revision_and_unsaved_start_body_do_not_dispatch_or_modify(setup):
    client, _, temporal = setup
    draft = _create(client, sentence="先保存").json()
    client.put(
        f"/v1/projects/{draft['project_id']}/draft",
        json={"draft_revision": 1, "sentence": "新版本"},
    )
    path = project_path(draft["project_id"]) / "project.json"
    before = path.read_bytes()
    assert _submit(client, draft).status_code == 409
    assert _submit(client, draft, sentence="未保存文本").status_code == 422
    assert (
        client.post(
            f"/v1/projects/{draft['project_id']}/film/start", json={"sentence": "旧接口"}
        ).status_code
        == 422
    )
    assert path.read_bytes() == before and temporal.calls == []


def _shot_project(client, ident):
    draft = _create(client, sentence="镜头草稿").json()
    save_node(draft["project_id"], "n05_storyboard", {"script": storyboard(shot())})
    return draft["project_id"]


def test_shot_save_persists_without_generation_and_next_n6_reads_saved_narration(
    setup, monkeypatch
):
    client, ident, temporal = setup
    project_id = _shot_project(client, ident)
    saved = client.patch(
        f"/v1/projects/{project_id}/canvas/nodes/shot:S01",
        json={"data": {"narration": "新的旁白", "prompt_suffix": "柔和侧光"}},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["narration"] == "新的旁白"
    assert saved.json()["data"]["prompt_suffix"] == "柔和侧光"
    assert temporal.calls == []
    from workers.workflow import activities

    original = storyboard(shot())
    seen = {}

    def fake_call(_run, request, _node):
        seen.update(request["payload"])
        return SimpleNamespace(payload={"script": request["payload"]["script"], "voiceovers": []})

    monkeypatch.setattr(activities, "_announce", lambda *_: 1)
    monkeypatch.setattr(activities, "_call", fake_call)
    result = activities.n06_voiceover(
        {
            "project_id": project_id,
            "request": {"enterprise_id": ident.enterprise_id},
            "state": {"script": original},
        }
    )
    assert seen["script"]["shots"][0]["voiceover"] == "新的旁白"
    assert seen["script"]["shots"][0]["visual"] == original["shots"][0]["visual"]
    assert result["patch"]["script"]["shots"][0]["voiceover"] == "新的旁白"
    assert original["shots"][0]["voiceover"] != "新的旁白"


@pytest.mark.parametrize(
    "data",
    [
        {"narration": None},
        {"narration": 42},
        {"narration": "x" * 401},
        {"prompt_suffix": "x" * 501},
        {"narration": "x\x00"},
        {"qa_passed": True},
        {},
    ],
)
def test_invalid_shot_patch_is_rejected_before_any_canvas_write(setup, data):
    client, ident, temporal = setup
    project_id = _shot_project(client, ident)
    path = project_path(project_id) / "canvas.json"
    response = client.patch(f"/v1/projects/{project_id}/canvas/nodes/shot:S01", json={"data": data})
    assert response.status_code == 422, response.text
    assert not path.exists() and temporal.calls == []


def test_other_member_of_same_tenant_does_not_replace_project_owner(setup):
    client, ident, temporal = setup
    draft = _create(client, sentence="负责人保持不变").json()
    colleague = mint_session_for_tests(ident.enterprise_id)
    teammate = TestClient(app, headers={"Authorization": f"Bearer {colleague.token}"})
    assert _submit(teammate, draft).status_code == 202
    assert read_snapshot(draft["project_id"])["owner_member_id"] == ident.member_id
    assert len(temporal.calls) == 1


def test_legacy_blank_keeps_owner_and_uses_single_submission_claim(setup):
    client, ident, temporal = setup
    project_id = client.post("/v1/projects/blank", json={"sentence": ""}).json()["project_id"]
    started = client.post(
        f"/v1/projects/{project_id}/film/start", json={"sentence": "兼容原画布入口"}
    )
    assert started.status_code == 202 and started.json()["submission_state"] == "submitted"
    assert read_snapshot(project_id)["owner_member_id"] == ident.member_id
    assert temporal.calls[0]["request"]["sentence"] == "兼容原画布入口"


def test_normal_create_passes_owner_to_existing_workflow_service(setup, monkeypatch):
    client, ident, _ = setup
    seen = {}

    async def fake_start(**kwargs):
        seen.update(kwargs)
        return "fixture-workflow"

    monkeypatch.setattr("app.projects.start_film", fake_start)
    assert client.post("/v1/projects", json={"sentence": "旧入口仍兼容"}).status_code == 202
    assert seen["owner_member_id"] == ident.member_id
