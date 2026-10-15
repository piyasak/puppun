"""Posting grants may be public ("everyone") as well as "only you" (Q-49, PO 2026-10-15).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-15
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widens the allowed values only: every existing row stays valid (expand-only, E-49).
    op.drop_constraint("ck_posting_grants_visibility", "posting_grants", type_="check")
    op.create_check_constraint("ck_posting_grants_visibility", "posting_grants", "visibility IN ('only_me', 'everyone')")


def downgrade() -> None:
    op.drop_constraint("ck_posting_grants_visibility", "posting_grants", type_="check")
    op.create_check_constraint("ck_posting_grants_visibility", "posting_grants", "visibility IN ('only_me')")
