"""SPEC §3.3 paths exist at the repository root (the hilatv/ tree)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = (
    "SPEC.md",
    "AGENTS.md",
    "apps/web",
    "apps/api",
    "workers/workflow",
    "workers/nodes/n01_brief/node.py",
    "workers/nodes/n01_brief/prompts",
    "workers/nodes/n01_brief/schema.py",
    "workers/schemas/__init__.py",
    "alembic.ini",
    "migrations/env.py",
    "workers/nodes/n01_brief/qa.py",
    "workers/nodes/n01_brief/tests",
    "workers/nodes/n04_script/node.py",
    "workers/nodes/n04_script/qa.py",
    "workers/nodes/n05_storyboard/node.py",
    "workers/nodes/n05_storyboard/qa.py",
    "templates/shots/slow_push_in.yaml",
    "workers/media",
    "workers/qa",
    "gateway/adapters",
    "gateway/router.py",
    "templates/industries",
    "templates/shots",
    "templates/packaging",
    "eval/briefs",
    "eval/run_eval.py",
    "infra/docker-compose.yml",
    ".env.example",
    "docs/licenses.md",
)


def test_spec_tree_exists() -> None:
    missing = [rel for rel in REQUIRED if not (ROOT / rel).exists()]
    assert missing == []


def test_compose_services_declare_healthchecks() -> None:
    text = (ROOT / "infra/docker-compose.yml").read_text(encoding="utf-8")
    for service in ("postgres:", "redis:", "minio:", "temporal:", "temporal-ui:"):
        assert service in text
    assert text.count("healthcheck:") >= 5


def test_stubs_import() -> None:
    from eval.run_eval import build_report
    from workers.media.ffmpeg import render_not_ready
    from workers.qa.service import review_not_ready
    from workers.workflow.pipeline import planned_nodes

    assert planned_nodes()[0] == "n01_brief"
    assert len(planned_nodes()) == 18
    assert build_report()["task"] == "T18"
    assert render_not_ready()["task"] == "T09"
    assert review_not_ready()["task"] == "T12"
