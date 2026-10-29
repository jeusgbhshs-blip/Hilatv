"""Gateway call logs and budget alerts.

Revision ID: t03_gateway_0002
Revises: t02_business_0001
Create Date: 2026-10-29

Column types match the SQLite tables the unit tests create in process.
Postgres must reach this revision through Alembic; the gateway does not
create these tables itself.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "t03_gateway_0002"
down_revision = "t02_business_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_logs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=True),
        sa.Column("node", sa.Text(), nullable=True),
        sa.Column("shot_id", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("params", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_cny", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("cache_hit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("qa_score", sa.Text(), nullable=True),
        sa.Column("live", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_call_logs"),
    )
    op.create_index("ix_call_logs_day", "call_logs", ["day"])
    op.create_index("ix_call_logs_seq", "call_logs", ["seq"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("spent_cny", sa.Text(), nullable=False),
        sa.Column("limit_cny", sa.Text(), nullable=False),
        sa.Column("daily_spent_cny", sa.Text(), nullable=True),
        sa.Column("daily_limit_cny", sa.Text(), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
    )


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_index("ix_call_logs_seq", table_name="call_logs")
    op.drop_index("ix_call_logs_day", table_name="call_logs")
    op.drop_table("call_logs")
