"""Posts at once per Environment (Q-54, PO 2026-10-23): the device limit by default, settable lower.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49): one nullable column; NULL = as many as the Environment's phones.
    op.add_column("environments", sa.Column("max_parallel_posts", sa.Integer()))
    op.create_check_constraint("ck_environments_parallel_posts", "environments",
                               "max_parallel_posts IS NULL OR max_parallel_posts >= 1")


def downgrade() -> None:
    op.drop_constraint("ck_environments_parallel_posts", "environments", type_="check")
    op.drop_column("environments", "max_parallel_posts")
