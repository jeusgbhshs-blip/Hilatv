"""Expert canvas document: positions, edges, and the structured timeline.

Revision ID: r02_canvas_0003
Revises: t03_gateway_0002
Create Date: 2026-10-31

The running API reads ``canvas.json`` in the project directory. This table is
the Postgres copy written when ``HILATV_CANVAS_DB=1``. ``ai_label`` cannot be
stored as false.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "r02_canvas_0003"
down_revision = "t03_gateway_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canvas_documents",
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("layout_version", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("project_id", name="pk_canvas_documents"),
        sa.ForeignKeyConstraint(
            ["enterprise_id"],
            ["enterprises.enterprise_id"],
            name="fk_canvas_documents_enterprise",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("layout_version >= 0", name="ck_canvas_documents_version"),
        sa.CheckConstraint(
            "jsonb_typeof(document) = 'object'",
            name="ck_canvas_documents_object",
        ),
        sa.CheckConstraint(
            "(document->>'layout_version')::int = layout_version",
            name="ck_canvas_documents_version_match",
        ),
        sa.CheckConstraint(
            "document->>'ai_label' IS NULL OR document->>'ai_label' = 'true'",
            name="ck_canvas_documents_ai_label",
        ),
    )
    op.create_index(
        "ix_canvas_documents_enterprise_id",
        "canvas_documents",
        ["enterprise_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_canvas_documents_enterprise_id", table_name="canvas_documents")
    op.drop_table("canvas_documents")
