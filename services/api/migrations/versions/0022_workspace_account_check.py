"""Whether the Agent checks the phone's TikTok account before and after a real post (Q-48, PO
2026-10-13). On by default; only a platform admin turns it off for a Workspace, with a reason (audited).
Off: the account is not checked, a posting grant of the Workspace covers any account, and the post is
verified by its caption marker only.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49): every existing Workspace keeps the check.
    op.add_column("workspaces", sa.Column("account_check", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("workspaces", "account_check")
