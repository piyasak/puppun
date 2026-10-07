"""P2.6: devices bound to Environments; one active binding per serial.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("serial", sa.String(64), nullable=False),
        sa.Column("serial_key", sa.String(64), nullable=False),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("android_version", sa.String(16), nullable=True),
        sa.Column("display_name", sa.String(60), nullable=True),
        sa.Column("expected_account", sa.String(64), nullable=True),
        sa.Column("registered_by", sa.Uuid(), sa.ForeignKey("agent_installations.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("last_state", sa.String(16), nullable=True),
        sa.Column("last_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_devices_workspace_id", "devices", ["workspace_id"])
    op.create_index("ix_devices_environment_id", "devices", ["environment_id"])
    op.create_index("uq_devices_active_serial", "devices", ["serial_key"], unique=True,
                    postgresql_where=sa.text("unbound_at IS NULL"))


def downgrade() -> None:
    op.drop_table("devices")
