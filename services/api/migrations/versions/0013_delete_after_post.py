"""Delete a clip's file on the Agent's PC once it is posted, if the job says so (PO 2026-10-10).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49): defaults keep every existing job and clip as it was.
    op.add_column("jobs", sa.Column("delete_after_post", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("clips", sa.Column("agent_installation_id", sa.Uuid(),
                                     sa.ForeignKey("agent_installations.id", ondelete="SET NULL"), nullable=True))
    op.add_column("clips", sa.Column("agent_file_deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("clips", "agent_file_deleted_at")
    op.drop_column("clips", "agent_installation_id")
    op.drop_column("jobs", "delete_after_post")
