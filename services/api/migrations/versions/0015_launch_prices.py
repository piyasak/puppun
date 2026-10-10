"""Launch prices (PO 2026-10-10, D05): a free 5-day trial and three monthly plans.

    trial     free, 5 days,   1 PC, 1 phone,   30 clips
    starter   200 THB/month,  1 PC, 5 phones,  1,000 clips
    pro       400 THB/month,  1 PC, 10 phones, 2,000 clips
    business  888 THB/month,  1 PC, 20 phones, unlimited clips (clips_per_month NULL)

New versions of the existing codes (plans are never edited in place, P6.5): running subscriptions
keep the version they started on until they renew. Real payments stay closed until G6-01/G6-02;
checkout is the sandbox provider.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-10
"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# code, name, price (satang), days, PCs, phones, clips (None = unlimited), purchasable
LAUNCH = [
    ("trial", "ทดลองฟรี 5 วัน", 0, 5, 1, 1, 30, False),
    ("starter", "Starter", 20000, 30, 1, 5, 1000, True),
    ("pro", "Pro", 40000, 30, 1, 10, 2000, True),
    ("business", "Business", 88800, 30, 1, 20, None, True),
]


def upgrade() -> None:
    op.alter_column("plans", "clips_per_month", existing_type=sa.Integer(), nullable=True)  # NULL = unlimited
    conn = op.get_bind()
    for code, name, price, days, pcs, phones, clips, purchasable in LAUNCH:
        latest = conn.execute(sa.text("SELECT coalesce(max(version), 0) FROM plans WHERE code = :c"), {"c": code}).scalar()
        conn.execute(sa.text(
            "INSERT INTO plans (id, code, version, name, is_demo, max_registered_agents, max_concurrent_sessions, "
            "max_devices, clips_per_month, price_satang, currency, interval_days, is_purchasable, retention_days) "
            "VALUES (:id, :code, :version, :name, false, :pcs, :pcs, :phones, :clips, :price, 'THB', :days, "
            ":purchasable, 30)"),
            {"id": uuid.uuid4(), "code": code, "version": latest + 1, "name": name, "pcs": pcs, "phones": phones,
             "clips": clips, "price": price, "days": days, "purchasable": purchasable})
        # One purchasable version per plan (as the Admin page does): the example prices stop being sold
        conn.execute(sa.text("UPDATE plans SET is_purchasable = false WHERE code = :c AND version <= :v"),
                     {"c": code, "v": latest})


def downgrade() -> None:
    # Non-destructive: the launch rows stay (subscriptions and payments may point at them); only the
    # schema goes back. "Unlimited" becomes a cap no customer reaches in a month.
    op.execute("UPDATE plans SET clips_per_month = 1000000 WHERE clips_per_month IS NULL")
    op.alter_column("plans", "clips_per_month", existing_type=sa.Integer(), nullable=False)
