"""Series title and hashtags set when a job is made (PO 2026-10-11): every clip's first caption is
"<title> — ตอนที่ i/N" with these hashtags, so auto mode needs no edit before posting.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49)
    op.add_column("jobs", sa.Column("caption_title", sa.String(100), nullable=True))
    op.add_column("jobs", sa.Column("caption_hashtags", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "caption_hashtags")
    op.drop_column("jobs", "caption_title")
