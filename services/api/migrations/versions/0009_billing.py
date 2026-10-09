"""P6.1-P6.3: prices on plans (examples, D05 open), subscription cycles, payments and provider events.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-09

Quota cycles move from calendar months to subscription cycles: the ledger period becomes the cycle's
exact start in UTC (billing.cycle_key). Existing month rows ('YYYY-MM') become the start of that month
in Asia/Bangkok, and existing subscriptions get the current calendar month as their first cycle, so
nothing changes for them now.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# Example plans only: prices from the original UI mock (PRD §8: "ตัวอย่าง"), caps invented for testing.
# Never sold until D05 is decided (is_demo = True keeps them out of real enrolment).
EXAMPLE_PLANS = [
    ("starter", "Starter (ตัวอย่าง — ราคายังไม่อนุมัติ)", 49000, 1, 1, 1, 60),
    ("pro", "Pro (ตัวอย่าง — ราคายังไม่อนุมัติ)", 99000, 2, 2, 3, 150),
    ("business", "Business (ตัวอย่าง — ราคายังไม่อนุมัติ)", 299000, 5, 5, 10, 500),
]


def upgrade() -> None:
    op.add_column("plans", sa.Column("price_satang", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("plans", sa.Column("currency", sa.String(3), nullable=False, server_default="THB"))
    op.add_column("plans", sa.Column("interval_days", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("plans", sa.Column("is_purchasable", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("plans", sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"))
    plans = sa.table("plans", sa.column("id", sa.Uuid()), sa.column("code", sa.String()), sa.column("version", sa.Integer()),
                     sa.column("name", sa.String()), sa.column("is_demo", sa.Boolean()),
                     sa.column("max_registered_agents", sa.Integer()), sa.column("max_concurrent_sessions", sa.Integer()),
                     sa.column("max_devices", sa.Integer()), sa.column("clips_per_month", sa.Integer()),
                     sa.column("price_satang", sa.Integer()), sa.column("is_purchasable", sa.Boolean()))
    import uuid

    op.bulk_insert(plans, [
        {"id": uuid.uuid4(), "code": code, "version": 1, "name": name, "is_demo": True, "price_satang": price,
         "max_registered_agents": agents, "max_concurrent_sessions": sessions, "max_devices": devices,
         "clips_per_month": clips, "is_purchasable": True}
        for code, name, price, agents, sessions, devices, clips in EXAMPLE_PLANS])

    op.add_column("subscriptions", sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subscriptions", sa.Column("paid_cycles_ahead", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("subscriptions", sa.Column("next_plan_id", sa.Uuid(), sa.ForeignKey("plans.id"), nullable=True))
    op.add_column("subscriptions", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                                             nullable=False))
    op.execute("""
        UPDATE subscriptions SET
          status = 'trial',
          current_period_start = (date_trunc('month', now() AT TIME ZONE 'Asia/Bangkok') AT TIME ZONE 'Asia/Bangkok'),
          current_period_end = ((date_trunc('month', now() AT TIME ZONE 'Asia/Bangkok') + interval '1 month')
                                AT TIME ZONE 'Asia/Bangkok')
    """)
    op.alter_column("subscriptions", "current_period_start", nullable=False)
    op.alter_column("subscriptions", "current_period_end", nullable=False)

    month_start = ("to_char(((({col} || '-01')::timestamp) AT TIME ZONE 'Asia/Bangkok') AT TIME ZONE 'UTC', "
                   "'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')")
    op.alter_column("quota_ledger", "period", type_=sa.String(40))
    op.execute(f"UPDATE quota_ledger SET period = {month_start.format(col='period')} WHERE length(period) = 7")
    op.alter_column("jobs", "quota_period", type_=sa.String(40))
    op.execute(f"UPDATE jobs SET quota_period = {month_start.format(col='quota_period')} WHERE length(quota_period) = 7")

    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", sa.Uuid(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("amount_satang", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("provider_ref", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("applied", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "provider_ref"),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
        sa.CheckConstraint("amount_satang > 0", name="ck_payments_amount_positive"),
    )
    op.create_index("ix_payments_workspace_id", "payments", ["workspace_id"])
    op.create_table(
        "payment_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("event_id", sa.String(80), nullable=False),
        sa.Column("payment_id", sa.Uuid(), sa.ForeignKey("payments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "event_id"),
    )
    op.create_index("ix_payment_events_payment_id", "payment_events", ["payment_id"])


def downgrade() -> None:
    op.drop_table("payment_events")
    op.drop_table("payments")
    op.execute("UPDATE jobs SET quota_period = to_char((quota_period::timestamptz) AT TIME ZONE 'Asia/Bangkok', "
               "'YYYY-MM') WHERE quota_period IS NOT NULL")
    op.alter_column("jobs", "quota_period", type_=sa.String(7))
    op.execute("UPDATE quota_ledger SET period = to_char((period::timestamptz) AT TIME ZONE 'Asia/Bangkok', 'YYYY-MM')")
    op.alter_column("quota_ledger", "period", type_=sa.String(7))
    for col in ("updated_at", "next_plan_id", "paid_cycles_ahead", "current_period_end", "current_period_start"):
        op.drop_column("subscriptions", col)
    op.execute("UPDATE subscriptions SET status = 'active'")
    op.execute("UPDATE subscriptions SET plan_id = (SELECT id FROM plans WHERE code = 'trial' ORDER BY version DESC LIMIT 1) "
               "WHERE plan_id IN (SELECT id FROM plans WHERE code IN ('starter', 'pro', 'business'))")
    op.execute("DELETE FROM plans WHERE code IN ('starter', 'pro', 'business')")
    for col in ("retention_days", "is_purchasable", "interval_days", "currency", "price_satang"):
        op.drop_column("plans", col)
