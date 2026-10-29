import json
import os
import subprocess
import sys
from pathlib import Path


def test_cli_rerun(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    output = tmp_path / "out.json"
    source.write_text(
        json.dumps(
            {"project_id": "cli-1", "payload": {"raw_input": "给数控机床做一条产品宣传片"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["HILATV_LIVE"] = "0"
    env["HILATV_GATEWAY_STORE"] = "sqlite"
    env["HILATV_SQLITE_PATH"] = str(tmp_path / "gateway.sqlite")
    env["PYTHONPATH"] = os.getcwd()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "workers.nodes.n01_brief",
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["ok"] is True
    assert saved["payload"]["brief"]["video_type"] == "product_showcase"
