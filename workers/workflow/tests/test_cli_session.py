"""The CLI takes enterprise_id from the session or the stored project."""

from __future__ import annotations

from workers.identity.session import mint_session_for_tests, open_session
from workers.workflow.cli import main
from workers.workflow.store import init_project, project_path


def test_run_without_a_session_stops(monkeypatch) -> None:
    monkeypatch.delenv("HILATV_SESSION", raising=False)
    assert main(["run", "做一条片"]) == 2


def test_rerun_rejects_another_enterprise(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HILATV_SESSION_SECRET", "cli-test")
    monkeypatch.delenv("HILATV_SESSION", raising=False)
    owner = open_session()
    other = mint_session_for_tests("55555555-5555-4555-8555-555555555555")
    init_project(
        "clirun1",
        sentence="本企业的句子",
        status="running",
        enterprise_id=owner.enterprise_id,
    )
    path = project_path("clirun1") / "project.json"
    before = path.read_bytes()
    assert main(["rerun", "--session", other.token, "clirun1", "n01_brief"]) == 2
    assert "项目不存在" in capsys.readouterr().err
    assert path.read_bytes() == before
    assert main(["rerun", "--session", owner.token, "clirun1", "n01_brief"]) == 2
    assert "项目仍在运行" in capsys.readouterr().err
    assert path.read_bytes() == before
