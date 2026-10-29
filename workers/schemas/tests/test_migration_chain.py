"""Alembic has one head, and this revision does not create gateway log tables."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[3]
REVISION = ROOT / "migrations" / "versions" / "20261029_0001_t02_business_tables.py"


def test_single_alembic_head() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    assert len(heads) == 1
    revisions = {rev.revision for rev in script.walk_revisions()}
    assert "t02_business_0001" in revisions


def test_business_migration_skips_gateway_log_tables() -> None:
    text = REVISION.read_text(encoding="utf-8")
    assert "call_logs" not in text
    assert "alerts" not in text
    for table in (
        "enterprises",
        "brand_kits",
        "briefs",
        "scripts",
        "shots",
        "assets",
        "candidates",
        "qa_reports",
        "director_decisions",
    ):
        assert table in text
