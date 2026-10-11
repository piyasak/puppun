"""What is in each Environment's videos folder (PO 2026-10-11): full videos to cut, and folders of
clips already cut, as last reported by its Agent. Names and sizes only, never paths.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49)
    op.create_table(
        "agent_libraries",
        sa.Column("environment_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("environments.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("installation_ref", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("agent_installations.id", ondelete="SET NULL")),
        sa.Column("videos", postgresql.JSONB(), nullable=False),
        sa.Column("sets", postgresql.JSONB(), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_libraries")
