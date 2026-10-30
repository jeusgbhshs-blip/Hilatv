"""N16 blocks planted flaws, requires logo and CTA, and does not release an unreviewed live film."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from workers.nodes.n16_final_review.node import run
from workers.nodes.n16_final_review.qa import QAError
from workers.nodes.n16_final_review.support import brand_elements, request_for, write_film
from workers.qa.budget_store import open_project_budget, project_folder
from workers.qa.samples import _plate
from workers.schemas.director import DirectorDecision
from workers.workflow.store import init_project, read_snapshot

_FORBIDDEN = ("补拍", "实拍", "reshoot", "customer_footage", "omit_ai_label")


def _png(path: Path, image: Image.Image) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return str(path)


def _three(tmp_path: Path) -> dict:
    anchor = _png(tmp_path / "t22flaw" / "anchor.png", _plate("rect"))
    frames = [_plate("rect"), _plate("shear"), _plate("rect")]
    film = write_film("t22flaw", frames)
    return request_for(
        "t22flaw",
        film,
        ["S01", "S02", "S03"],
        seconds_each=0.25,
        anchors={"S02": anchor},
    )


def test_hard_flaw_is_located_and_only_that_shot_is_redone(gateway, tmp_path: Path) -> None:
    result = run(_three(tmp_path), gateway=gateway)
    body = result.payload
    flaws = [item for item in body["issues"] if item["kind"] == "hard_flaw"]
    assert flaws
    assert {item["shot_id"] for item in flaws} == {"S02"}
    assert "product_deform" in {item["code"] for item in flaws}
    assert body["release"] is False
    assert body["disposition"] == "redo"
    assert body["visual_reviewed"] is False
    assert body["vlm_total"] == "未测"
    assert body["budget_taken"] == 1
    decisions = [DirectorDecision.model_validate(item) for item in body["decisions"]]
    assert [item.target.shot_id for item in decisions] == ["S02"]
    assert all(item.target.node == "N10" for item in decisions)
    blob = json.dumps(body["decisions"], ensure_ascii=False)
    assert all(word not in blob for word in _FORBIDDEN)
    assert decisions[0].changes["source"] == "ai_generated"
    used = json.loads((project_folder("t22flaw") / "regen_budget.json").read_text(encoding="utf-8"))
    assert used["used"] == 1
    tasks = {row["task"] for row in gateway.store.list_logs(project_id="t22flaw")}
    assert {"judge", "asr", "content_safety"} <= tasks


def test_clean_film_releases_without_a_rerun(gateway, tmp_path: Path) -> None:
    init_project("t22clean", sentence="一句", enterprise_id="ent-clean")
    film = write_film("t22clean", [_plate("rect")])
    raw = request_for("t22clean", film, ["S01"], seconds_each=1.0)
    raw["payload"]["enterprise_id"] = "from-body"
    result = run(raw, gateway=gateway)
    body = result.payload
    assert body["release"] is True
    assert body["disposition"] == "release"
    assert body["decisions"] == []
    assert body["budget_taken"] == 0
    assert body["visual_reviewed"] is False
    assert "未测" in body["qa"]["notes"]
    assert body["enterprise_id"] == "ent-clean"
    assert not (project_folder("t22clean") / "regen_budget.json").is_file()
    snapshot = read_snapshot("t22clean") or {}
    assert snapshot.get("status") != "needs_human_review"
    assert snapshot.get("deliverable") is None


def test_missing_logo_and_missing_cta_are_flagged(gateway, tmp_path: Path) -> None:
    film = write_film("t22logo", [_plate("rect")])
    no_logo = request_for(
        "t22logo",
        film,
        ["S01"],
        seconds_each=1.0,
        elements=brand_elements(logo=False),
    )
    logo = run(no_logo, gateway=gateway)
    assert logo.payload["release"] is False
    assert logo.payload["brand"]["complete"] is False
    assert any(item["code"] == "missing_logo" for item in logo.payload["issues"])
    assert logo.payload["decisions"] == []

    film_cta = write_film("t22cta", [_plate("rect")])
    no_cta = request_for(
        "t22cta",
        film_cta,
        ["S01"],
        seconds_each=1.0,
        elements=brand_elements(cta=False),
    )
    cta = run(no_cta, gateway=gateway)
    assert any(item["code"] == "missing_cta" for item in cta.payload["issues"])
    assert cta.payload["release"] is False
    assert cta.payload["decisions"] == []


def test_budget_exhaustion_refuses_the_regen(gateway, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "1")
    raw = _three(tmp_path)
    assert open_project_budget("t22flaw").try_take() is True
    result = run(raw, gateway=gateway)
    body = result.payload
    assert body["release"] is False
    assert body["disposition"] == "hold"
    assert body["decisions"] == []
    assert body["budget_taken"] == 0
    assert any(
        item["code"] == "budget_exhausted" and item["shot_id"] == "S02" for item in body["issues"]
    )
    used = json.loads((project_folder("t22flaw") / "regen_budget.json").read_text(encoding="utf-8"))
    assert used["used"] == 1


def test_live_unreviewed_film_holds_and_delivery_is_blocked(
    gateway, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HILATV_SESSION_SECRET", "t22-live-session")
    monkeypatch.setenv("HILATV_LIVE", "1")
    from workers.identity.session import open_session

    owner = open_session()
    other = open_session()
    init_project(
        "t22live",
        sentence="一句",
        status="completed",
        deliverable=str(tmp_path / "t22live" / "master.mp4"),
        enterprise_id=owner.enterprise_id,
    )
    film = write_film("t22live", [_plate("rect")])
    result = run(request_for("t22live", film, ["S01"], seconds_each=1.0), gateway=gateway)
    assert result.payload["release"] is False
    assert result.payload["disposition"] == "hold"
    assert result.payload["visual_reviewed"] is False
    assert result.payload["decisions"] == []
    assert result.payload["enterprise_id"] == owner.enterprise_id
    assert result.payload["brand"]["logo_pixels"] == "未测"
    assert result.payload["brand"]["cta_pixels"] == "未测"
    assert result.payload["film_judge"]["usable"] is False
    snapshot = read_snapshot("t22live") or {}
    assert snapshot["status"] == "needs_human_review"
    assert not snapshot.get("deliverable")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        denied = client.post(
            "/v1/projects/t22live/deliveries",
            json={},
            headers={"Authorization": f"Bearer {owner.token}"},
        )
        assert denied.status_code == 409
        hidden = client.post(
            "/v1/projects/t22live/deliveries",
            json={},
            headers={"Authorization": f"Bearer {other.token}"},
        )
        assert hidden.status_code == 404
    assert not (tmp_path / "t22live" / "deliveries.json").is_file()


def test_extreme_words_use_the_compliance_module_and_do_not_regen(gateway, tmp_path: Path) -> None:
    film = write_film("t22word", [_plate("rect")])
    raw = request_for("t22word", film, ["S01", "S02"], seconds_each=0.25)
    raw["payload"]["script"]["shots"][1]["voiceover"] = "这是最好的柱塞泵。"
    result = run(raw, gateway=gateway)
    words = [item for item in result.payload["issues"] if item["code"] == "extreme_words"]
    assert words
    assert words[0]["shot_id"] == "S02"
    assert result.payload["release"] is False
    assert result.payload["decisions"] == []
    assert result.payload["compliance"]["passed"] is False


def test_removing_the_ai_label_is_rejected(gateway, tmp_path: Path) -> None:
    film = write_film("t22label", [_plate("rect")])
    raw = request_for(
        "t22label",
        film,
        ["S01"],
        seconds_each=1.0,
        elements=brand_elements(ai_label=False),
    )
    missing = run(raw, gateway=gateway)
    assert missing.payload["release"] is False
    assert any(item["code"] == "missing_ai_label" for item in missing.payload["issues"])
    raw["payload"]["omit_ai_label"] = True
    with pytest.raises(QAError):
        run(raw, gateway=gateway)


def test_unsafe_text_is_not_released(gateway, tmp_path: Path) -> None:
    film = write_film("t22unsafe", [_plate("rect")])
    raw = request_for("t22unsafe", film, ["S01"], seconds_each=1.0)
    raw["payload"]["brief"]["raw_input"] = "HILATV_UNSAFE_SAMPLE 请做一条片子"
    result = run(raw, gateway=gateway)
    assert result.payload["release"] is False
    assert result.payload["compliance"]["blocked"] is True
    assert result.payload["decisions"] == []


def _owned_master(tmp_path: Path, project_id: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HILATV_SESSION_SECRET", f"t22-{project_id}")
    monkeypatch.setenv("HILATV_LIVE", "1")
    from workers.identity.session import open_session

    owner = open_session()
    other = open_session()
    master = tmp_path / project_id / "master.mp4"
    init_project(
        project_id,
        sentence="一句",
        status="completed",
        deliverable=str(master),
        enterprise_id=owner.enterprise_id,
    )
    return owner, other


def _deliveries(project_id: str, owner_token: str, other_token: str) -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        denied = client.post(
            f"/v1/projects/{project_id}/deliveries",
            json={},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert denied.status_code == 409
        hidden = client.post(
            f"/v1/projects/{project_id}/deliveries",
            json={},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert hidden.status_code == 404


def test_live_flaw_holds_an_existing_master(gateway, tmp_path: Path, monkeypatch) -> None:
    owner, other = _owned_master(tmp_path, "t22held", monkeypatch)
    anchor = _png(tmp_path / "t22held" / "anchor.png", _plate("rect"))
    film = write_film("t22held", [_plate("rect"), _plate("shear"), _plate("rect")])
    raw = request_for(
        "t22held",
        film,
        ["S01", "S02", "S03"],
        seconds_each=0.25,
        anchors={"S02": anchor},
    )
    result = run(raw, gateway=gateway)
    body = result.payload
    assert body["release"] is False
    assert body["disposition"] == "hold"
    assert [item["target"]["shot_id"] for item in body["decisions"]] == ["S02"]
    assert body["budget_taken"] == 1
    assert body["brand"]["logo_pixels"] == "未测"
    snapshot = read_snapshot("t22held") or {}
    assert snapshot["status"] == "needs_human_review"
    assert not snapshot.get("deliverable")
    _deliveries("t22held", owner.token, other.token)
    used = json.loads((project_folder("t22held") / "regen_budget.json").read_text(encoding="utf-8"))
    assert used["used"] == 1


def test_live_asr_failure_holds_the_master(gateway, tmp_path: Path, monkeypatch) -> None:
    owner, other = _owned_master(tmp_path, "t22asr", monkeypatch)

    def broken_asr(*_args, **_kwargs):
        raise RuntimeError("asr down")

    gateway.asr = broken_asr
    film = write_film("t22asr", [_plate("rect")])
    result = run(request_for("t22asr", film, ["S01"], seconds_each=1.0), gateway=gateway)
    assert result.payload["release"] is False
    assert result.payload["disposition"] == "hold"
    assert result.payload["asr"]["failed"] is True
    snapshot = read_snapshot("t22asr") or {}
    assert snapshot["status"] == "needs_human_review"
    assert not snapshot.get("deliverable")
    _deliveries("t22asr", owner.token, other.token)


def test_live_shot_review_error_holds_the_master(gateway, tmp_path: Path, monkeypatch) -> None:
    owner, other = _owned_master(tmp_path, "t22shot", monkeypatch)

    def explode(*_args, **_kwargs):
        raise RuntimeError("shot review failed")

    monkeypatch.setattr("workers.nodes.n16_final_review.node.review_shot", explode)
    film = write_film("t22shot", [_plate("rect")])
    result = run(request_for("t22shot", film, ["S01"], seconds_each=1.0), gateway=gateway)
    assert result.payload["release"] is False
    assert result.payload["disposition"] == "hold"
    assert any(item["code"] == "shot_review_failed" for item in result.payload["issues"])
    snapshot = read_snapshot("t22shot") or {}
    assert snapshot["status"] == "needs_human_review"
    assert not snapshot.get("deliverable")
    _deliveries("t22shot", owner.token, other.token)


def test_short_budget_takes_nothing(gateway, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "1")
    anchor = _png(tmp_path / "t22pair" / "anchor.png", _plate("rect"))
    film = write_film("t22pair", [_plate("shear"), _plate("shear")])
    raw = request_for(
        "t22pair",
        film,
        ["S01", "S02"],
        seconds_each=0.25,
        anchors={"S01": anchor, "S02": anchor},
    )
    init_project("t22pair", sentence="一句", status="completed", deliverable=str(film))
    result = run(raw, gateway=gateway)
    assert result.payload["budget_taken"] == 0
    assert result.payload["decisions"] == []
    assert result.payload["disposition"] == "hold"
    assert any(item["code"] == "budget_exhausted" for item in result.payload["issues"])
    used = json.loads((project_folder("t22pair") / "regen_budget.json").read_text(encoding="utf-8"))
    assert used["used"] == 0


def test_concurrent_reviews_charge_one_shot(tmp_path: Path, monkeypatch) -> None:
    import threading

    from workers.nodes.n16_final_review.tests.conftest import build_gateway

    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "1")
    anchor = _png(tmp_path / "t22race" / "anchor.png", _plate("rect"))
    film = write_film("t22race", [_plate("rect"), _plate("shear"), _plate("rect")])
    raw = request_for(
        "t22race",
        film,
        ["S01", "S02", "S03"],
        seconds_each=0.25,
        anchors={"S02": anchor},
    )
    gateways = [build_gateway(tmp_path / "gw-a"), build_gateway(tmp_path / "gw-b")]
    start = threading.Barrier(2)
    taken: list[int] = []

    def worker(index: int) -> None:
        start.wait()
        body = run(raw, gateway=gateways[index]).payload
        taken.append(int(body["budget_taken"]))

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(taken) == [0, 1]
    used = json.loads((project_folder("t22race") / "regen_budget.json").read_text(encoding="utf-8"))
    assert used["used"] == 1


def test_n10_does_not_charge_the_redo_again(gateway, tmp_path: Path) -> None:
    result = run(_three(tmp_path), gateway=gateway)
    assert result.payload["budget_taken"] == 1
    from workers.nodes.media_gateway import build_media_gateway
    from workers.nodes.n08_keyframe.node import run as run_keyframes
    from workers.nodes.n08_keyframe.tests.shots import request, shot
    from workers.nodes.n10_video.node import run as run_video

    media_dir = tmp_path / "n10-gw"
    media_dir.mkdir()
    media = build_media_gateway(media_dir)
    frames = run_keyframes(request(shot()), gateway=media)
    before = open_project_budget("t22flaw").used
    run_video(
        {
            "project_id": "t22flaw",
            "payload": {
                "script": frames.payload["script"],
                "candidates": frames.payload["candidates"],
                "video_candidates": 3,
            },
        },
        gateway=media,
    )
    assert open_project_budget("t22flaw").used == before == 1
