"""SPEC documents survive a JSONB write once `make accept-t02` has migrated."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest

from workers.schemas import (
    Asset,
    AssetKind,
    BrandKit,
    Brief,
    Candidate,
    DirectorDecision,
    Script,
    Shot,
)
from workers.schemas.tests.conftest import load_fixture

pytest.importorskip("psycopg")


def _require_db() -> str:
    if os.environ.get("HILATV_REQUIRE_DB") != "1":
        pytest.skip("database roundtrip runs under make accept-t02")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        pytest.fail("HILATV_REQUIRE_DB=1 but DATABASE_URL is empty")
    return url


def _as_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        loaded = json.loads(value)
    else:
        loaded = value
    assert isinstance(loaded, dict)
    return loaded


def test_documents_roundtrip_through_jsonb() -> None:
    import psycopg
    from psycopg.types.json import Jsonb

    url = _require_db()
    try:
        conn = psycopg.connect(url, connect_timeout=5)
    except psycopg.Error as exc:
        pytest.fail(f"Postgres is not reachable: {exc}")

    enterprise_id = uuid.uuid4()
    qa_report_id = uuid.uuid4()
    decision_id = uuid.uuid4()
    brand = BrandKit.model_validate(load_fixture("brand_kit.json"))
    brief = Brief.model_validate(load_fixture("brief.json"))
    shot = Shot.model_validate(load_fixture("shot.json"))
    script = Script(script_id="script-1", brief_id=brief.brief_id, language="en", shots=[shot])
    candidate = Candidate.model_validate(load_fixture("candidate.json"))
    decision = DirectorDecision.model_validate(load_fixture("director_decision.json"))
    asset = Asset(
        asset_id="asset-1",
        kind=AssetKind.cutout,
        uri="oss://cutout.png",
        brand_id="uuid",
    )

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename IN ('call_logs', 'alerts')
                """
            )
            assert cur.fetchall() == []

            cur.execute(
                "INSERT INTO enterprises (enterprise_id, name) VALUES (%s, %s)",
                (enterprise_id, "青岛某某机械有限公司"),
            )
            cur.execute(
                """
                INSERT INTO brand_kits (brand_id, enterprise_id, document)
                VALUES (%s, %s, %s)
                """,
                (brand.brand_id, enterprise_id, Jsonb(brand.model_dump(mode="json"))),
            )
            cur.execute(
                """
                INSERT INTO briefs (brief_id, enterprise_id, brand_id, document)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    brief.brief_id,
                    enterprise_id,
                    brand.brand_id,
                    Jsonb(brief.model_dump(mode="json")),
                ),
            )
            cur.execute(
                """
                INSERT INTO scripts (script_id, enterprise_id, brief_id, document)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    script.script_id,
                    enterprise_id,
                    brief.brief_id,
                    Jsonb(script.model_dump(mode="json")),
                ),
            )
            cur.execute(
                """
                INSERT INTO shots (script_id, shot_id, enterprise_id, document)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    script.script_id,
                    shot.shot_id,
                    enterprise_id,
                    Jsonb(shot.model_dump(mode="json")),
                ),
            )
            cur.execute(
                """
                INSERT INTO assets (asset_id, enterprise_id, brand_id, shot_id, document)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    asset.asset_id,
                    enterprise_id,
                    asset.brand_id,
                    asset.shot_id,
                    Jsonb(asset.model_dump(mode="json")),
                ),
            )
            cur.execute(
                """
                INSERT INTO candidates (candidate_id, enterprise_id, shot_id, document)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    candidate.candidate_id,
                    enterprise_id,
                    candidate.shot_id,
                    Jsonb(candidate.model_dump(mode="json")),
                ),
            )
            cur.execute(
                """
                INSERT INTO qa_reports (qa_report_id, enterprise_id, candidate_id, document)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    qa_report_id,
                    enterprise_id,
                    candidate.candidate_id,
                    Jsonb(candidate.qa.model_dump(mode="json")),
                ),
            )
            cur.execute(
                """
                INSERT INTO director_decisions (decision_id, enterprise_id, document)
                VALUES (%s, %s, %s)
                """,
                (decision_id, enterprise_id, Jsonb(decision.model_dump(mode="json"))),
            )

            cur.execute("SELECT document FROM brand_kits WHERE brand_id = %s", (brand.brand_id,))
            loaded_brand = BrandKit.model_validate(_as_obj(cur.fetchone()[0]))
            assert loaded_brand.model_dump(mode="json") == brand.model_dump(mode="json")

            cur.execute("SELECT document FROM shots WHERE shot_id = %s", (shot.shot_id,))
            loaded_shot = Shot.model_validate(_as_obj(cur.fetchone()[0]))
            assert loaded_shot.model_dump(mode="json") == shot.model_dump(mode="json")
            assert loaded_shot.on_screen_text[0].in_ == 0.8

            cur.execute(
                "SELECT document FROM candidates WHERE candidate_id = %s",
                (candidate.candidate_id,),
            )
            loaded_candidate = Candidate.model_validate(_as_obj(cur.fetchone()[0]))
            assert loaded_candidate.qa.total == candidate.qa.total
            assert loaded_candidate.params["seed"] == 1234

            cur.execute("SAVEPOINT bad_mode")
            with pytest.raises(psycopg.Error):
                bad_shot = shot.model_dump(mode="json")
                bad_shot["generation_mode"] = "ken_burns"
                cur.execute(
                    """
                    INSERT INTO shots (script_id, shot_id, enterprise_id, document)
                    VALUES (%s, %s, %s, %s)
                    """,
                    ("script-1", "S99", enterprise_id, Jsonb(bad_shot)),
                )
            cur.execute("ROLLBACK TO SAVEPOINT bad_mode")

            cur.execute("SAVEPOINT bad_id")
            with pytest.raises(psycopg.Error):
                cur.execute(
                    """
                    INSERT INTO brand_kits (brand_id, enterprise_id, document)
                    VALUES (%s, %s, %s)
                    """,
                    ("other", enterprise_id, Jsonb(brand.model_dump(mode="json"))),
                )
            cur.execute("ROLLBACK TO SAVEPOINT bad_id")
    finally:
        conn.rollback()
        conn.close()
