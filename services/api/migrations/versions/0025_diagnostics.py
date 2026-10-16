"""Phone screen diagnostics (PO 2026-10-16): screenshots + screen readings from the Agent, kept 7 days.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49): a new table.
    op.create_table(
        "diagnostics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("devices.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("schedule_items.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("check", sa.String(40)),
        sa.Column("code", sa.String(40)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.String(300)),
        sa.Column("files", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_diagnostics_workspace_id", "diagnostics", ["workspace_id"])
    op.create_index("ix_diagnostics_device_id", "diagnostics", ["device_id"])
    op.create_index("ix_diagnostics_expires_at", "diagnostics", ["expires_at"])


def downgrade() -> None:
    op.drop_table("diagnostics")
