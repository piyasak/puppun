"""Room for Stripe ids (D06): a Checkout Session id is "cs_test_" / "cs_live_" + ~58 characters,
longer than the 64 the sandbox refs needed, so saving one failed with a 500 on staging.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand-only (E-49): widening a varchar does not rewrite the table
    op.alter_column("payments", "provider_ref", type_=sa.String(255), existing_type=sa.String(64),
                    existing_nullable=False)


def downgrade() -> None:
    pass  # non-destructive: narrowing back would fail on (or cut) stored Stripe ids
