"""Exercise acceptance environment isolation and the full pytest collection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_accept_environment_never_executes_developer_env_or_inherits_live_destinations(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (fixture / ".env.example").write_text(
        "HILATV_LIVE=1\nHILATV_BUDGET_CNY=99\nHILATV_DAILY_BUDGET_CNY=99\n",
        encoding="utf-8",
    )
    malicious = fixture / ".env"
    malicious.write_text('printf executed > "$CANARY"\n', encoding="utf-8")
    canary = tmp_path / "canary"
    env = {
        **os.environ,
        "ROOT": str(fixture),
        "TMPDIR": str(scratch),
        "CANARY": str(canary),
        "ENV_FILE": str(malicious),
        "ARK_API_KEY": "fake-key-to-strip",
        "CUSTOM_VENDOR_SECRET": "fake-secret-to-strip",
        "S3_ENDPOINT": "https://production-storage.invalid",
        "S3_ACCESS_KEY": "fake-inherited-storage-key",
        "HILATV_PROJECT_DIR": str(tmp_path / "existing-projects"),
        "HILATV_PROGRESS_PATH": str(tmp_path / "existing-progress.md"),
        "HILATV_CANVAS_DB": "1",
        "PYTEST_ADDOPTS": "--ignore=workers",
    }
    names = [
        "ENV_FILE",
        "HILATV_LIVE",
        "HILATV_BUDGET_CNY",
        "HILATV_DAILY_BUDGET_CNY",
        "ARK_API_KEY",
        "CUSTOM_VENDOR_SECRET",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "HILATV_PROJECT_DIR",
        "HILATV_BRAND_DIR",
        "HILATV_PROGRESS_PATH",
        "HILATV_SQLITE_PATH",
        "HILATV_ACCEPT_WORK_DIR",
        "HILATV_CANVAS_DB",
        "PYTEST_ADDOPTS",
        "PYTHONPATH",
    ]
    inspect = f"import json, os; print(json.dumps({{k:os.getenv(k) for k in {names!r}}}))"
    completed = subprocess.run(
        [
            "bash",
            "-euc",
            'source "$1"; exec "$2" -c "$3"',
            "accept-env-test",
            str(ROOT / "infra/scripts/accept_env.sh"),
            sys.executable,
            inspect,
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert not canary.exists()
    assert result["ENV_FILE"] == str(fixture / ".env.example")
    for name in ("HILATV_LIVE", "HILATV_BUDGET_CNY", "HILATV_DAILY_BUDGET_CNY", "HILATV_CANVAS_DB"):
        assert result[name] == "0"
    for name in (
        "ARK_API_KEY",
        "CUSTOM_VENDOR_SECRET",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "PYTEST_ADDOPTS",
    ):
        assert result[name] is None
    work = Path(result["HILATV_ACCEPT_WORK_DIR"])
    assert work.is_dir() and work.is_relative_to(scratch)
    for name in (
        "HILATV_PROJECT_DIR",
        "HILATV_BRAND_DIR",
        "HILATV_PROGRESS_PATH",
        "HILATV_SQLITE_PATH",
    ):
        assert Path(result[name]).is_relative_to(work)
    assert result["PYTHONPATH"].split(os.pathsep)[:2] == [str(fixture), str(fixture / "apps/api")]


def test_every_shell_acceptance_uses_the_same_safe_environment_loader():
    for path in (ROOT / "infra/scripts").glob("accept*.sh"):
        if path.name == "accept_env.sh":
            continue
        text = path.read_text(encoding="utf-8")
        assert 'source "$ROOT/infra/scripts/accept_env.sh"' in text, path.name
        assert 'source "$ENV_FILE"' not in text, path.name


def test_default_collection_includes_n7_without_duplicate_test_module_conflicts(tmp_path):
    env = {
        **os.environ,
        "PYTHONPATH": f"{ROOT}{os.pathsep}{ROOT / 'apps/api'}",
        "HILATV_LIVE": "0",
        "HILATV_BUDGET_CNY": "0",
        "HILATV_DAILY_BUDGET_CNY": "0",
        "HILATV_PROJECT_DIR": str(tmp_path / "projects"),
    }
    env.pop("PYTEST_ADDOPTS", None)
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts="],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert collected.returncode == 0, collected.stdout[-6000:] + collected.stderr[-2000:]
    assert "workers/nodes/n07_anchor/tests/test_node.py::" in collected.stdout
    assert "workers/nodes/n01_brief/tests/test_node.py::" in collected.stdout
    assert "gateway/tests/test_budget_atomic.py::" in collected.stdout
    assert "apps/api/tests/test_project_drafts.py::" in collected.stdout
