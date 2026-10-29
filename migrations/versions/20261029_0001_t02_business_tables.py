"""Business JSONB documents for SPEC chapters 4 and 5.

Revision ID: t02_business_0001
Revises:
Create Date: 2026-10-29

Gateway invocation logs are a later revision. This file only creates the
enterprise boundary and the chapter 4 / 5 documents.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from workers.schemas.director import DecisionAction
from workers.schemas.script import GenerationMode

revision = "t02_business_0001"
down_revision = None
branch_labels = None
depends_on = None


def _sql_in(expression: str, values: Sequence[str]) -> str:
    quoted = ", ".join("'" + value.replace("'", "''") + "'" for value in values)
    return f"{expression} IN ({quoted})"


def _timestamps() -> list[sa.Column[sa.DateTime]]:
    stamp = sa.DateTime(timezone=True)
    return [
        sa.Column("created_at", stamp, nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", stamp, nullable=False, server_default=sa.text("now()")),
    ]


def _enterprise_id() -> sa.Column[postgresql.UUID]:
    return sa.Column("enterprise_id", postgresql.UUID(as_uuid=True), nullable=False)


def _document() -> sa.Column[postgresql.JSONB]:
    return sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False)


def _enterprise_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["enterprise_id"],
        ["enterprises.enterprise_id"],
        name=name,
        ondelete="CASCADE",
    )


def _object_check(table: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        "jsonb_typeof(document) = 'object'",
        name=f"ck_{table}_document_object",
    )


def _id_check(table: str, column: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(
        f"document->>'{column}' = {column}",
        name=f"ck_{table}_id",
    )


def _index_enterprise(table: str) -> None:
    op.create_index(f"ix_{table}_enterprise_id", table, ["enterprise_id"])


def _index_document(table: str) -> None:
    op.create_index(f"ix_{table}_document", table, ["document"], postgresql_using="gin")


def upgrade() -> None:
    op.create_table(
        "enterprises",
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("enterprise_id", name="pk_enterprises"),
    )

    op.create_table(
        "brand_kits",
        sa.Column("brand_id", sa.Text(), nullable=False),
        _enterprise_id(),
        _document(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("brand_id", name="pk_brand_kits"),
        _enterprise_fk("fk_brand_kits_enterprise"),
        _object_check("brand_kits"),
        _id_check("brand_kits", "brand_id"),
    )
    _index_enterprise("brand_kits")
    _index_document("brand_kits")

    op.create_table(
        "briefs",
        sa.Column("brief_id", sa.Text(), nullable=False),
        _enterprise_id(),
        sa.Column("brand_id", sa.Text(), nullable=True),
        _document(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("brief_id", name="pk_briefs"),
        _enterprise_fk("fk_briefs_enterprise"),
        _object_check("briefs"),
        _id_check("briefs", "brief_id"),
    )
    _index_enterprise("briefs")
    op.create_index("ix_briefs_brand_id", "briefs", ["brand_id"])
    _index_document("briefs")

    op.create_table(
        "scripts",
        sa.Column("script_id", sa.Text(), nullable=False),
        _enterprise_id(),
        sa.Column("brief_id", sa.Text(), nullable=True),
        _document(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("script_id", name="pk_scripts"),
        _enterprise_fk("fk_scripts_enterprise"),
        _object_check("scripts"),
        _id_check("scripts", "script_id"),
    )
    _index_enterprise("scripts")
    op.create_index("ix_scripts_brief_id", "scripts", ["brief_id"])
    _index_document("scripts")

    op.create_table(
        "shots",
        sa.Column("script_id", sa.Text(), nullable=False),
        sa.Column("shot_id", sa.Text(), nullable=False),
        _enterprise_id(),
        _document(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("script_id", "shot_id", name="pk_shots"),
        _enterprise_fk("fk_shots_enterprise"),
        _object_check("shots"),
        _id_check("shots", "shot_id"),
        sa.CheckConstraint(
            _sql_in(
                "document->>'generation_mode'",
                [mode.value for mode in GenerationMode],
            ),
            name="ck_shots_generation_mode",
        ),
    )
    _index_enterprise("shots")
    op.create_index("ix_shots_shot_id", "shots", ["shot_id"])
    _index_document("shots")

    op.create_table(
        "assets",
        sa.Column("asset_id", sa.Text(), nullable=False),
        _enterprise_id(),
        sa.Column("brand_id", sa.Text(), nullable=True),
        sa.Column("shot_id", sa.Text(), nullable=True),
        _document(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("asset_id", name="pk_assets"),
        _enterprise_fk("fk_assets_enterprise"),
        _object_check("assets"),
        _id_check("assets", "asset_id"),
    )
    _index_enterprise("assets")
    op.create_index("ix_assets_brand_id", "assets", ["brand_id"])
    op.create_index("ix_assets_shot_id", "assets", ["shot_id"])
    _index_document("assets")

    op.create_table(
        "candidates",
        sa.Column("candidate_id", sa.Text(), nullable=False),
        _enterprise_id(),
        sa.Column("shot_id", sa.Text(), nullable=False),
        _document(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("candidate_id", name="pk_candidates"),
        _enterprise_fk("fk_candidates_enterprise"),
        _object_check("candidates"),
        _id_check("candidates", "candidate_id"),
        sa.CheckConstraint(
            "document->>'shot_id' = shot_id",
            name="ck_candidates_shot_id",
        ),
        sa.CheckConstraint(
            "document->>'node' ~ '^N([1-9]|1[0-8])$'",
            name="ck_candidates_node",
        ),
    )
    _index_enterprise("candidates")
    op.create_index("ix_candidates_shot_id", "candidates", ["shot_id"])
    _index_document("candidates")

    op.create_table(
        "qa_reports",
        sa.Column("qa_report_id", postgresql.UUID(as_uuid=True), nullable=False),
        _enterprise_id(),
        sa.Column("candidate_id", sa.Text(), nullable=True),
        _document(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("qa_report_id", name="pk_qa_reports"),
        _enterprise_fk("fk_qa_reports_enterprise"),
        _object_check("qa_reports"),
    )
    _index_enterprise("qa_reports")
    op.create_index("ix_qa_reports_candidate_id", "qa_reports", ["candidate_id"])
    _index_document("qa_reports")

    op.create_table(
        "director_decisions",
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        _enterprise_id(),
        _document(),
        *_timestamps(),
        sa.PrimaryKeyConstraint("decision_id", name="pk_director_decisions"),
        _enterprise_fk("fk_director_decisions_enterprise"),
        _object_check("director_decisions"),
        sa.CheckConstraint(
            _sql_in("document->>'action'", [action.value for action in DecisionAction]),
            name="ck_director_decisions_action",
        ),
        sa.CheckConstraint(
            "document->'target'->>'node' ~ '^N([1-9]|1[0-8])$'",
            name="ck_director_decisions_node",
        ),
    )
    _index_enterprise("director_decisions")
    _index_document("director_decisions")


def downgrade() -> None:
    op.drop_table("director_decisions")
    op.drop_table("qa_reports")
    op.drop_table("candidates")
    op.drop_table("assets")
    op.drop_table("shots")
    op.drop_table("scripts")
    op.drop_table("briefs")
    op.drop_table("brand_kits")
    op.drop_table("enterprises")
