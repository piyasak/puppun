"""Authorized real posting (Q-42): admin-issued grants per Workspace + TikTok account, and the posting
mode each schedule item was handed out with.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49)
    op.create_table(
        "posting_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("account", sa.String(64), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("max_posts", sa.Integer(), nullable=False),
        sa.Column("used_posts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.CheckConstraint("max_posts BETWEEN 1 AND 1000", name="ck_posting_grants_max"),
        sa.CheckConstraint("used_posts >= 0 AND used_posts <= max_posts", name="ck_posting_grants_used"),
        sa.CheckConstraint("visibility IN ('only_me')", name="ck_posting_grants_visibility"),
    )
    op.add_column("schedule_items", sa.Column("posting_mode", sa.String(8), nullable=True))
    op.add_column("schedule_items", sa.Column("grant_id", postgresql.UUID(as_uuid=True),
                                              sa.ForeignKey("posting_grants.id", ondelete="SET NULL"), nullable=True))
    op.add_column("schedule_items", sa.Column("grant_used", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("schedule_items", "grant_used")
    op.drop_column("schedule_items", "grant_id")
    op.drop_column("schedule_items", "posting_mode")
    op.drop_table("posting_grants")
