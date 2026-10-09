"""Q-32: the clip count can follow the source (whole-source split), up to 100 clips per job.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (staging rollback = redeploy, E-49): a new column with a default, a wider check.
    op.add_column("jobs", sa.Column("auto_clips", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_constraint("ck_jobs_requested_clips", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_requested_clips", "jobs", "requested_clips BETWEEN 1 AND 100")


def downgrade() -> None:
    op.execute("UPDATE jobs SET requested_clips = 20 WHERE requested_clips > 20")
    op.drop_constraint("ck_jobs_requested_clips", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_requested_clips", "jobs", "requested_clips BETWEEN 1 AND 20")
    op.drop_column("jobs", "auto_clips")
