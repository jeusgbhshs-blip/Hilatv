import json

import pytest

from eval.run_eval import build_report, main


def test_report_is_stub() -> None:
    report = build_report()
    assert report["status"] == "stub"
    assert report["task"] == "T18"
    assert report["cases"] == 0


def test_main_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main() == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["scores"] == {}
