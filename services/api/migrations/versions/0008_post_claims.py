"""P4.3: post claims: lease, delivery count, evidence, Agent events.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schedule_items", sa.Column("lease_session_id", sa.Uuid(),
                                              sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True))
    op.add_column("schedule_items", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("schedule_items", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("schedule_items", "attempts", server_default=None)
    op.add_column("schedule_items", sa.Column("evidence", JSONB(), nullable=True))
    op.create_table(
        "schedule_item_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("schedule_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(24), nullable=False),
        sa.Column("detail", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("item_id", "event_id"),
    )
    op.create_index("ix_schedule_item_events_workspace_id", "schedule_item_events", ["workspace_id"])
    op.create_index("ix_schedule_item_events_item_id", "schedule_item_events", ["item_id"])


def downgrade() -> None:
    op.drop_table("schedule_item_events")
    for col in ("evidence", "attempts", "lease_expires_at", "lease_session_id"):
        op.drop_column("schedule_items", col)
