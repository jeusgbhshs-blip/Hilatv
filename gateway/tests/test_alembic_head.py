"""call_logs and alerts are the single Alembic head after T02."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
REVISION = ROOT / "migrations" / "versions" / "20261029_0002_t03_gateway_logs.py"


def test_single_head_is_gateway_logs() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["t03_gateway_0002"]
    revision = script.get_revision("t03_gateway_0002")
    assert revision is not None
    assert revision.down_revision == "t02_business_0001"
    text = REVISION.read_text(encoding="utf-8")
    assert "call_logs" in text
    assert "alerts" in text
    assert not (ROOT / "gateway" / "db").exists()
