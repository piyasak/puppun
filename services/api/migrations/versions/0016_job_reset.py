"""Start a job again (PO 2026-10-10): the owner or an admin can restart a job whose clip files went
missing on the Agent's PC (moved folder, new location) or whose source could not be read.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49)
    op.add_column("jobs", sa.Column("remake_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("reset_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("jobs", "reset_count")
    op.drop_column("jobs", "remake_requested_at")
