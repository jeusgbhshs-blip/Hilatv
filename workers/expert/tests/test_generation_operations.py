"""New intentions vary seeds; transport retries never repeat generation or counts."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from gateway.adapters.mock_adapter import MockAdapter
from gateway.media_bytes import render_png
from gateway.storage import MemoryObjectStore
from gateway.tests.conftest import build_gateway, mock_llm_routes
from workers.expert.charge import BudgetExhausted, reserve_picture
from workers.expert.desk import add_node, load_doc
from workers.expert.gates import GateError
from workers.expert.node_generate import generate_node
from workers.expert.operations import OperationConflict
from workers.expert.shot_action import regenerate_shot, set_reference
from workers.identity.session import open_session
from workers.nodes.n08_keyframe.tests.shots import shot, storyboard
from workers.nodes.runtime import candidate_uuid, placeholder_qa, variant_seeds
from workers.qa.budget_store import open_project_budget
from workers.schemas.asset import Candidate
from workers.workflow.store import init_project, load_checkpoint, project_path, save_node


class CountingGateway:
    def __init__(self, *, fail=False, delay=0.0):
        self.calls = []
        self.fail, self.delay = fail, delay
        self.lock = threading.Lock()

    def _call(self, kind, **kwargs):
        with self.lock:
            self.calls.append((kind, kwargs))
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise TimeoutError("provider result unknown")
        return {
            "uri": f"mock://{kind}/{kwargs['seed']}",
            "model": f"mock-{kind}",
            "mock": True,
            "seed": kwargs["seed"],
        }

    def generate_image(self, prompt, **kwargs):
        return self._call("image", **kwargs)

    def generate_video(self, prompt, **kwargs):
        return self._call("video", **kwargs)


def _project(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "8")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    owner = open_session()
    init_project("p1", status="draft", enterprise_id=owner.enterprise_id)
    node = add_node(
        "p1",
        {"kind": "image", "position": {"x": 0, "y": 0}, "data": {"prompt": "金属产品，无文字"}},
        enterprise_id=owner.enterprise_id,
    )
    return owner, node["id"]


def _candidate(result, node_id):
    return next(node for node in result["canvas"]["nodes"] if node["id"] == node_id)["data"][
        "candidates"
    ]


def test_new_attempt_varies_actual_gateway_seed_uri_and_retains_old_candidates(
    tmp_path, monkeypatch
):
    _, node_id = _project(tmp_path, monkeypatch)
    engine = build_gateway(tmp_path, routes=mock_llm_routes())
    first = generate_node("p1", node_id, {"operation_id": "new-1"}, gateway=engine)
    replay = generate_node("p1", node_id, {"operation_id": "new-1"}, gateway=engine)
    assert replay["generation_id"] == first["generation_id"] and replay["replayed"] is True
    assert _candidate(first, node_id) == _candidate(replay, node_id)
    assert len(engine.store.list_logs()) == 1
    second = generate_node("p1", node_id, {"operation_id": "new-2"}, gateway=engine)
    rows = _candidate(second, node_id)
    assert len(rows) == 2 and rows[0] == _candidate(first, node_id)[0]
    assert rows[0]["seed"] != rows[1]["seed"]
    assert rows[0]["uri"] != rows[1]["uri"]
    assert rows[0]["candidate_id"] != rows[1]["candidate_id"]
    assert all(row["execution_mode"] == "mock" and row["verdict"] == "unreviewed" for row in rows)
    assert all(not log["cache_hit"] for log in engine.store.list_logs())
    records = [
        json.loads(path.read_text())
        for path in (project_path("p1") / "generation_operations").glob("*.json")
    ]
    assert {record["input_revision"] for record in records} == {1, 2}
    assert all(record["input_hash"] and record["input_snapshot"]["prompt"] for record in records)


@pytest.mark.parametrize("changed", [{"prompt": "改成夜景"}, {"count": 2}])
def test_changed_input_for_same_operation_conflicts_before_call(tmp_path, monkeypatch, changed):
    _, node_id = _project(tmp_path, monkeypatch)
    engine = CountingGateway()
    generate_node("p1", node_id, {"operation_id": "one"}, gateway=engine)
    with pytest.raises(OperationConflict) as error:
        generate_node("p1", node_id, {"operation_id": "one", **changed}, gateway=engine)
    assert error.value.detail["code"] == "operation_input_conflict"
    assert len(engine.calls) == 1 and len(load_doc("p1").user_nodes[0].data["candidates"]) == 1


def test_two_threads_and_fresh_gateway_replay_one_result(tmp_path, monkeypatch):
    _, node_id = _project(tmp_path, monkeypatch)
    engine = CountingGateway(delay=0.03)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(generate_node, "p1", node_id, {"operation_id": "thread"}, gateway=engine)
            for _ in range(2)
        ]
        results = [future.result() for future in futures]
    assert len(engine.calls) == 1
    assert results[0]["generation_id"] == results[1]["generation_id"]
    fresh = CountingGateway(fail=True)
    replay = generate_node("p1", node_id, {"operation_id": "thread"}, gateway=fresh)
    assert replay["replayed"] is True and fresh.calls == []


def _process_generate(root, node_id, queue, crash=False):
    os.environ["HILATV_PROJECT_DIR"] = root
    os.environ["HILATV_LIVE"] = "0"
    os.environ.pop("DATABASE_URL", None)

    class Engine(CountingGateway):
        def generate_image(self, prompt, **kwargs):
            with (Path(root) / "provider-calls.txt").open("a") as handle:
                handle.write("submitted\n")
                handle.flush()
                os.fsync(handle.fileno())
            if crash:
                os._exit(17)
            return super().generate_image(prompt, **kwargs)

    try:
        result = generate_node("p1", node_id, {"operation_id": "process"}, gateway=Engine())
        queue.put(result["generation_id"])
    except GateError as exc:
        queue.put({"status": exc.status, "message": str(exc)})


def test_two_processes_only_submit_one_generation(tmp_path, monkeypatch):
    _, node_id = _project(tmp_path, monkeypatch)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=_process_generate, args=(str(tmp_path), node_id, queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(10)
        assert process.exitcode == 0
    assert queue.get(timeout=2) == queue.get(timeout=2)
    assert (tmp_path / "provider-calls.txt").read_text().splitlines() == ["submitted"]


def test_crashed_submission_is_unknown_and_never_resubmitted(tmp_path, monkeypatch):
    _, node_id = _project(tmp_path, monkeypatch)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(target=_process_generate, args=(str(tmp_path), node_id, queue, True))
    process.start()
    process.join(10)
    assert process.exitcode == 17
    engine = CountingGateway()
    with pytest.raises(OperationConflict) as error:
        generate_node("p1", node_id, {"operation_id": "process"}, gateway=engine)
    assert error.value.detail["code"] == "operation_result_unknown" and engine.calls == []
    assert load_doc("p1").user_nodes[0].data["candidates"] == []


def test_timeout_retry_and_api_contract_preserve_operation_identity(tmp_path, monkeypatch):
    owner, node_id = _project(tmp_path, monkeypatch)
    engine = CountingGateway(fail=True)
    monkeypatch.setattr("gateway.get_gateway", lambda: engine)
    client = TestClient(app, headers={"Authorization": f"Bearer {owner.token}"})
    url = f"/v1/projects/p1/canvas/nodes/{node_id}/generate"
    first = client.post(url, json={"operation_id": "timeout"})
    second = client.post(url, json={"operation_id": "timeout"})
    assert first.status_code == second.status_code == 409
    assert first.json()["detail"]["operation_id"] == "timeout"
    assert second.json()["detail"]["code"] == "operation_result_unknown"
    assert len(engine.calls) == 1
    assert client.post(url, json={"operation_id": "../bad"}).status_code == 422
    stranger = TestClient(app, headers={"Authorization": f"Bearer {open_session().token}"})
    assert stranger.post(url, json={"operation_id": "foreign"}).status_code == 404
    assert len(list((project_path("p1") / "generation_operations").glob("*.json"))) == 1


def _seed_shot():
    save_node("p1", "n05_storyboard", {"script": storyboard(shot())})


def _fake_picture_node(name, **kwargs):
    kind = "image" if name == "n08_keyframe" else "video"
    seed = variant_seeds("S01", kind, 1)[0]
    engine = kwargs["gateway"]
    method = engine.generate_image if kind == "image" else engine.generate_video
    output = method("金属产品，无文字", seed=seed, project_id="p1", node=name, shot_id="S01")
    candidate = Candidate(
        candidate_id=candidate_uuid("p1", "S01", name, kind, seed),
        shot_id="S01",
        node="N8" if kind == "image" else "N10",
        model=output["model"],
        params={"seed": seed, "frame": "first", "prompt": "金属产品，无文字"},
        uri=output["uri"],
        qa=placeholder_qa(selected=True),
        selected=True,
    ).model_dump(mode="json")
    return {"keyframes" if kind == "image" else "videos": [candidate]}


def test_shot_replay_charges_once_and_new_attempt_keeps_old_candidates(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    _seed_shot()
    monkeypatch.setattr("workers.expert.shot_action.invoke_node", _fake_picture_node)
    engine = CountingGateway()
    body = {"operation_id": "shot-one", "narration": "新的旁白。"}
    first = regenerate_shot("p1", "S01", body, gateway=engine)
    replay = regenerate_shot("p1", "S01", body, gateway=engine)
    assert first["generation_id"] == replay["generation_id"] and len(engine.calls) == 2
    assert open_project_budget("p1").used == 2
    second = regenerate_shot("p1", "S01", {**body, "operation_id": "shot-two"}, gateway=engine)
    assert len(engine.calls) == 4 and open_project_budget("p1").used == 4
    rows = next(item for item in second["canvas"]["shots"] if item["shot_id"] == "S01")
    assert len(rows["keyframes"]) == len(rows["videos"]) == 2
    assert rows["keyframes"][0]["candidate_id"] != rows["keyframes"][1]["candidate_id"]
    assert load_doc("p1").shots["S01"].regen_count == 4
    before = (project_path("p1") / "nodes/n05_storyboard.json").read_bytes()
    with pytest.raises(OperationConflict):
        regenerate_shot("p1", "S01", {**body, "narration": "不能借旧编号改输入"}, gateway=engine)
    assert (project_path("p1") / "nodes/n05_storyboard.json").read_bytes() == before


def test_budget_refusal_leaves_script_canvas_selections_and_media_unchanged(tmp_path, monkeypatch):
    owner, _ = _project(tmp_path, monkeypatch)
    _seed_shot()
    upload_id = "a" * 32
    upload = tmp_path / "uploads" / upload_id
    upload.mkdir(parents=True)
    (upload / ".enterprise").write_text(owner.enterprise_id)
    (upload / "reference.png").write_bytes(render_png(1))
    set_reference("p1", "S01", upload_id, enterprise_id=owner.enterprise_id)
    old = Candidate(
        candidate_id="old-selected",
        shot_id="S01",
        node="N8",
        model="mock-image",
        params={"seed": 1, "frame": "first"},
        uri="mock://old",
        qa=placeholder_qa(selected=True),
        selected=True,
    ).model_dump(mode="json")
    save_node("p1", "n08_keyframe", {"keyframes": [old]})
    directory = project_path("p1")
    media = directory / "media"
    media.mkdir()
    (media / "original.mp4").write_bytes(b"original film")
    budget = open_project_budget("p1")
    assert budget.try_take_n(budget.limit)
    paths = [
        directory / "nodes/n05_storyboard.json",
        directory / "nodes/n08_keyframe.json",
        directory / "canvas.json",
        media / "original.mp4",
    ]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    engine = CountingGateway()
    with pytest.raises(BudgetExhausted):
        regenerate_shot(
            "p1",
            "S01",
            {"operation_id": "refused", "narration": "不能提前写入。", "prompt_suffix": "新的提示"},
            gateway=engine,
        )
    assert before == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    assert engine.calls == [] and list(media.iterdir()) == [media / "original.mp4"]
    assert open_project_budget("p1").used == budget.limit


def test_project_picture_ledger_applies_operation_once(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    rows = [shot()]
    assert reserve_picture("p1", rows, "S01", operation_id="once") == 2
    assert reserve_picture("p1", rows, "S01", operation_id="once") == 2
    assert open_project_budget("p1").used == 2


def test_portrait_authorization_refuses_before_budget_or_narration_write(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path / "brands"))
    save_node(
        "p1",
        "n05_storyboard",
        {
            "script": storyboard(
                shot(
                    generation_mode="reference_to_video",
                    subject_refs=["person:missing"],
                )
            )
        },
    )
    path = project_path("p1") / "nodes/n05_storyboard.json"
    before = path.read_bytes()
    engine = CountingGateway()
    with pytest.raises(GateError, match="授权"):
        regenerate_shot(
            "p1", "S01", {"operation_id": "no-consent", "narration": "不可保存"}, gateway=engine
        )
    assert path.read_bytes() == before and engine.calls == []
    assert open_project_budget("p1").used == 0


def test_partial_multi_candidate_timeout_keeps_old_choices_and_blocks_retry(tmp_path, monkeypatch):
    _, node_id = _project(tmp_path, monkeypatch)

    class PartialGateway(CountingGateway):
        def generate_image(self, prompt, **kwargs):
            if len(self.calls) == 1:
                self.fail = True
            return super().generate_image(prompt, **kwargs)

    engine = PartialGateway()
    with pytest.raises(OperationConflict):
        generate_node("p1", node_id, {"operation_id": "partial", "count": 2}, gateway=engine)
    assert len(engine.calls) == 2 and load_doc("p1").user_nodes[0].data["candidates"] == []
    with pytest.raises(OperationConflict):
        generate_node("p1", node_id, {"operation_id": "partial", "count": 2}, gateway=engine)
    assert len(engine.calls) == 2


def test_missing_gateway_evidence_stays_unknown_in_candidate(tmp_path, monkeypatch):
    _, node_id = _project(tmp_path, monkeypatch)

    class UnmarkedGateway(CountingGateway):
        def generate_image(self, prompt, **kwargs):
            output = super().generate_image(prompt, **kwargs)
            output.pop("mock")
            return output

    result = generate_node(
        "p1", node_id, {"operation_id": "unknown-source"}, gateway=UnmarkedGateway()
    )
    candidate = _candidate(result, node_id)[0]
    assert candidate["execution_mode"] == "unknown"
    assert candidate["mock"] is None and candidate["cache_hit"] is None


def test_candidate_model_comes_from_actual_gateway_log_when_output_omits_it(tmp_path, monkeypatch):
    from types import SimpleNamespace

    _, node_id = _project(tmp_path, monkeypatch)

    class Engine(CountingGateway):
        def generate_image(self, prompt, **kwargs):
            self.calls.append(("image", kwargs))
            self.store = SimpleNamespace(
                list_logs=lambda **filters: [
                    {
                        "params": kwargs["params"],
                        "node": kwargs["node"],
                        "shot_id": None,
                        "model": "provider-image-v1",
                        "provider": "fixture-provider",
                        "cache_hit": False,
                    }
                ]
            )
            return {"uri": "oss://fixture/generated.png", "mock": False}

    result = generate_node("p1", node_id, {"operation_id": "actual-model"}, gateway=Engine())
    candidate = _candidate(result, node_id)[0]
    assert candidate["model"] == "provider-image-v1"
    assert candidate["provider"] == "fixture-provider"
    assert candidate["execution_mode"] == "live" and candidate["cache_hit"] is False


def test_real_n8_n10_parallel_generation_uses_new_identity_and_network_retry_does_not(
    tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch)
    _seed_shot()
    engine = build_gateway(
        tmp_path,
        routes=mock_llm_routes(),
        registry={"mock": MockAdapter(store=MemoryObjectStore())},
    )
    first = regenerate_shot("p1", "S01", {"operation_id": "real-one"}, gateway=engine)
    calls = len(engine.store.list_logs())
    replay = regenerate_shot("p1", "S01", {"operation_id": "real-one"}, gateway=engine)
    assert replay["generation_id"] == first["generation_id"]
    assert len(engine.store.list_logs()) == calls
    second = regenerate_shot("p1", "S01", {"operation_id": "real-two"}, gateway=engine)
    state = load_checkpoint("p1")
    for kind in ("keyframes", "videos"):
        old = [
            row for row in state[kind] if row["params"]["generation_id"] == first["generation_id"]
        ]
        new = [
            row for row in state[kind] if row["params"]["generation_id"] == second["generation_id"]
        ]
        assert len(old) == len(new) == 3
        assert set(row["uri"] for row in old).isdisjoint(row["uri"] for row in new)
        assert set(row["params"]["seed"] for row in old).isdisjoint(
            row["params"]["seed"] for row in new
        )
        assert not any(row["selected"] for row in old)
        assert all(row["params"]["execution_mode"] == "mock" for row in old + new)
    assert open_project_budget("p1").used == 4
