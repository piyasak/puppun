"""P6.4-P6.6: platform roles, audit reasons with before/after, retention of clip files.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # admin | support | NULL. Set only by the server-side CLI (clipflow_api.manage), never by the API.
    op.add_column("users", sa.Column("platform_role", sa.String(16), nullable=True))
    op.add_column("audit_events", sa.Column("reason", sa.String(500), nullable=True))
    op.add_column("audit_events", sa.Column("details", JSONB(), nullable=True))
    op.add_column("clips", sa.Column("file_deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("clips", "file_deleted_at")
    op.drop_column("audit_events", "details")
    op.drop_column("audit_events", "reason")
    op.drop_column("users", "platform_role")
