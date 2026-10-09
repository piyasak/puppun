"""Q-33: the clip file stays on the Agent's PC; the server keeps its checks and a still image.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49): new columns with defaults; clips delivered before keep "server".
    op.add_column("clips", sa.Column("file_location", sa.String(8), nullable=False, server_default="server"))
    op.add_column("clips", sa.Column("preview_key", sa.String(300), nullable=True))
    op.add_column("clips", sa.Column("agent_path", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("clips", "agent_path")
    op.drop_column("clips", "preview_key")
    op.drop_column("clips", "file_location")
