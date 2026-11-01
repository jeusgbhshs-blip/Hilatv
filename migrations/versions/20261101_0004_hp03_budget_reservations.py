"""Atomic in-flight money reservations, separate from settled provider call logs.

Revision ID: hp03_budget_0004
Revises: r02_canvas_0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "hp03_budget_0004"
down_revision = "r02_canvas_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "budget_reservations",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("day", sa.Text(), nullable=False),
        sa.Column("amount_cny", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_budget_reservations"),
    )
    op.create_index("ix_budget_reservations_state", "budget_reservations", ["state"])


def downgrade() -> None:
    # Never erase unresolved provider obligations during a rollback.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM budget_reservations WHERE state IN ('reserved', 'uncertain'))
            THEN RAISE EXCEPTION 'Reconcile gateway budget reservations before downgrade';
            END IF;
        END $$;
    """)
    op.drop_index("ix_budget_reservations_state", table_name="budget_reservations")
    op.drop_table("budget_reservations")
