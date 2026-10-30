"""The N16 rerun command uses the session. Another enterprise does not see the project."""

from __future__ import annotations

import json
from pathlib import Path

from workers.identity.session import mint_session_for_tests
from workers.nodes.n16_final_review.__main__ import main
from workers.workflow.store import init_project


def test_other_enterprise_is_not_found(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_SESSION_SECRET", "t22-cli-session")
    monkeypatch.delenv("HILATV_SESSION", raising=False)
    owner = mint_session_for_tests("11111111-1111-4111-8111-111111111111")
    other = mint_session_for_tests("22222222-2222-4222-8222-222222222222")
    init_project("t22cli", sentence="一句", enterprise_id=owner.enterprise_id)
    body = tmp_path / "request.json"
    body.write_text(
        json.dumps({"project_id": "t22cli", "payload": {"enterprise_id": "from-body"}}),
        encoding="utf-8",
    )
    missing = main(["--input", str(body)])
    assert missing == 2
    assert "需要登录会话" in capsys.readouterr().err

    hidden = main(["--input", str(body), "--session", other.token])
    assert hidden == 2
    assert "项目不存在" in capsys.readouterr().err

    owned = main(["--input", str(body), "--session", owner.token])
    assert owned == 1
    assert "项目不存在" not in capsys.readouterr().err


def test_conflict_is_not_reported_as_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_SESSION_SECRET", "t22-cli-conflict")
    monkeypatch.delenv("HILATV_SESSION", raising=False)
    from workers.identity.access import Conflict

    owner = mint_session_for_tests("11111111-1111-4111-8111-111111111111")
    init_project("t22cli2", sentence="一句", enterprise_id=owner.enterprise_id)
    body = tmp_path / "request.json"
    body.write_text(json.dumps({"project_id": "t22cli2", "payload": {}}), encoding="utf-8")

    def clash(_identity, _project_id):
        raise Conflict("项目不在人工复核")

    monkeypatch.setattr("workers.nodes.n16_final_review.__main__.project_for", clash)
    code = main(["--input", str(body), "--session", owner.token])
    assert code == 2
    err = capsys.readouterr().err
    assert "项目不在人工复核" in err
    assert "项目不存在" not in err
