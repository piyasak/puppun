"""Short pairing codes: link an Agent to an Environment without copying a token (PO 2026-10-10).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_pairing_codes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("environment_id", sa.Uuid(), sa.ForeignKey("environments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_id", sa.Uuid(), sa.ForeignKey("agent_tokens.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_pairing_codes_workspace_id", "agent_pairing_codes", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_pairing_codes_workspace_id", table_name="agent_pairing_codes")
    op.drop_table("agent_pairing_codes")
