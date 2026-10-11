"""Whether each phone has the Thai keyboard a live post types with (ADBKeyboard, Q-44), as last
reported by its Agent. NULL: the Agent did not say (older than 0.5.3).

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49)
    op.add_column("devices", sa.Column("thai_keyboard", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("devices", "thai_keyboard")
