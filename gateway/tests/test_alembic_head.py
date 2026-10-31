"""call_logs and alerts are the single Alembic head after T02."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
REVISION = ROOT / "migrations" / "versions" / "20261029_0002_t03_gateway_logs.py"


def test_single_head_is_gateway_logs() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["r02_canvas_0003"]
    gateway = script.get_revision("t03_gateway_0002")
    assert gateway is not None
    assert gateway.down_revision == "t02_business_0001"
    canvas = script.get_revision("r02_canvas_0003")
    assert canvas is not None
    assert canvas.down_revision == "t03_gateway_0002"
    text = REVISION.read_text(encoding="utf-8")
    assert "call_logs" in text
    assert "alerts" in text
    canvas_rev = (ROOT / "migrations" / "versions" / "20261031_0003_r2_canvas.py").read_text(
        encoding="utf-8"
    )
    assert "def upgrade" in canvas_rev
    assert "def downgrade" in canvas_rev
    assert "canvas_documents" in canvas_rev
    assert "ck_canvas_documents_ai_label" in canvas_rev
    assert not (ROOT / "gateway" / "db").exists()
