"""P3.2: clip files, server-side checks, metadata versions, approval.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("clips", sa.Column("storage_key", sa.String(300), nullable=True))
    op.add_column("clips", sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clips", sa.Column("check_status", sa.String(8), nullable=True))
    op.add_column("clips", sa.Column("check_results", JSONB(), nullable=True))
    op.add_column("clips", sa.Column("metadata_version", sa.Integer(), nullable=False, server_default="1"))
    op.alter_column("clips", "metadata_version", server_default=None)
    op.add_column("clips", sa.Column("approved_metadata_version", sa.Integer(), nullable=True))
    op.add_column("clips", sa.Column("approved_sha256", sa.String(64), nullable=True))
    op.add_column("clips", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clips", sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"),
                                     nullable=True))
    op.add_column("clips", sa.Column("approval_mode", sa.String(8), nullable=True))

    op.create_table(
        "clip_metadata",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clip_id", sa.Uuid(), sa.ForeignKey("clips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("caption", sa.String(2200), nullable=False),
        sa.Column("hashtags", JSONB(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("clip_id", "version"),
    )
    op.create_index("ix_clip_metadata_workspace_id", "clip_metadata", ["workspace_id"])
    op.create_index("ix_clip_metadata_clip_id", "clip_metadata", ["clip_id"])


def downgrade() -> None:
    op.drop_table("clip_metadata")
    for col in ("approval_mode", "approved_by", "approved_at", "approved_sha256", "approved_metadata_version",
                "metadata_version", "check_results", "check_status", "uploaded_at", "storage_key"):
        op.drop_column("clips", col)
