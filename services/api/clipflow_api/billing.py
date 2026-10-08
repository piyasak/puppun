"""Subscriptions, payments and the sandbox provider (P6.1–P6.3, FR-20, E-45).

Cycles: a subscription has one current cycle [start, end) and may have renewals already paid for
(`paid_cycles_ahead`) and a plan change waiting for the next cycle (`next_plan_id`, PRD §8: MVP
changes plans at the next cycle). `effective` works out where the subscription is at any moment
without writing; `roll` writes it, under the subscription row lock. The quota period is the cycle's
start date, so a new cycle starts a fresh quota exactly once (no double reset, G6-04).

Payments: the server computes amount, currency and plan version (PRD §F). A payment changes only
through a provider event whose signature verifies over the raw body; events are unique per
(provider, event_id) and statuses only move forward (pending -> succeeded/failed -> refunded), so
forged, repeated or late events never grant twice or roll a status back (G6-03). The browser's
return from checkout never grants anything.

Sandbox: the only provider until D06. It signs events with HMAC-SHA256 like a real provider would
and exists only outside production.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .errors import ApiError
from .models import Payment, PaymentEvent, Plan, Subscription

TZ = ZoneInfo("Asia/Bangkok")
ACTIVE = ("trial", "active")
STATUS_ORDER = {"pending": 0, "failed": 1, "succeeded": 2, "refunded": 3}
EVENT_STATUS = {"payment.pending": "pending", "payment.failed": "failed", "payment.succeeded": "succeeded",
                "payment.refunded": "refunded"}


def now() -> datetime:
    return datetime.now(UTC)


def cycle_key(start: datetime) -> str:
    return start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True)
class Cycle:
    start: datetime
    end: datetime
    plan: Plan
    status: str  # trial | active | expired
    paid_cycles_ahead: int
    next_plan: Plan | None

    @property
    def key(self) -> str:
        """Quota period of this cycle: its exact start (UTC, microseconds). A date alone is not enough:
        a trial and the first paid cycle usually start on the same day (found by test_billing)."""
        return cycle_key(self.start)

    @property
    def active(self) -> bool:
        return self.status in ACTIVE


def effective(db: Session, sub: Subscription, at: datetime) -> Cycle:
    plan = db.get(Plan, sub.plan_id)
    nxt = db.get(Plan, sub.next_plan_id) if sub.next_plan_id else None
    start, end, ahead, status = sub.current_period_start, sub.current_period_end, sub.paid_cycles_ahead, sub.status
    while at >= end and ahead > 0:  # paid renewals take over at the boundary, one cycle at a time
        plan, nxt = (nxt or plan), None
        start, end = end, end + timedelta(days=plan.interval_days)
        ahead -= 1
        status = "active"
    if at >= end:
        status = "expired"
    return Cycle(start, end, plan, status, ahead, nxt)


def roll(db: Session, sub: Subscription, at: datetime) -> Cycle:
    """Persist `effective`. The caller holds the subscription row lock."""
    c = effective(db, sub, at)
    if (sub.current_period_start, sub.plan_id, sub.status) != (c.start, c.plan.id, c.status):
        sub.current_period_start, sub.current_period_end, sub.plan_id = c.start, c.end, c.plan.id
        sub.paid_cycles_ahead, sub.next_plan_id = c.paid_cycles_ahead, c.next_plan.id if c.next_plan else None
        sub.status, sub.updated_at = c.status, at
    return c


def require_active(cycle: Cycle) -> None:
    if not cycle.active:
        raise ApiError(402, "SUBSCRIPTION_EXPIRED", "แพ็กเกจหมดอายุแล้ว ต่ออายุที่หน้าแพ็กเกจก่อนสร้างงานใหม่")


# --- checkout ---------------------------------------------------------------------------------

def purchasable(db: Session) -> list[Plan]:
    rows = db.scalars(select(Plan).where(Plan.is_purchasable.is_(True)).order_by(Plan.price_satang)).all()
    latest: dict[str, Plan] = {}
    for p in rows:
        if p.code not in latest or p.version > latest[p.code].version:
            latest[p.code] = p
    return sorted(latest.values(), key=lambda p: p.price_satang)


def checkout(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID, plan_code: str, idempotency_key: str,
             provider: str = "sandbox") -> tuple[Payment, bool]:
    existing = db.scalars(select(Payment).where(Payment.workspace_id == workspace_id,
                                                Payment.idempotency_key == idempotency_key)).first()
    if existing is not None:
        return existing, False
    plan = next((p for p in purchasable(db) if p.code == plan_code), None)
    if plan is None:
        raise ApiError(404, "PLAN_NOT_FOUND", "ไม่พบแพ็กเกจนี้")
    sub = db.scalars(select(Subscription).where(Subscription.workspace_id == workspace_id)).one()
    cycle = effective(db, sub, now())
    if cycle.active and cycle.next_plan and cycle.next_plan.id != plan.id:
        raise ApiError(409, "CHANGE_PENDING", "มีการเปลี่ยนแพ็กเกจรอรอบถัดไปอยู่แล้ว")
    at = now()
    payment = Payment(workspace_id=workspace_id, plan_id=plan.id, amount_satang=plan.price_satang,
                      currency=plan.currency, provider=provider, provider_ref=f"sbx_{secrets.token_hex(12)}",
                      status="pending", idempotency_key=idempotency_key, created_by=user_id, created_at=at, updated_at=at)
    db.add(payment)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.scalars(select(Payment).where(Payment.workspace_id == workspace_id,
                                                Payment.idempotency_key == idempotency_key)).one(), False
    return payment, True


# --- provider events --------------------------------------------------------------------------

def sign(secret: bytes, body: bytes) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify(secret: bytes, body: bytes, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign(secret, body), signature.strip().lower())


def handle_event(db: Session, provider: str, body: bytes) -> dict:
    """Apply one verified provider event. Returns what happened (for the response and the log)."""
    try:
        event = json.loads(body)
        event_id, kind, ref = str(event["event_id"]), str(event["type"]), str(event["provider_ref"])
        amount, currency = int(event["amount"]), str(event["currency"])
    except (KeyError, TypeError, ValueError):
        raise ApiError(400, "BAD_EVENT", "รูปแบบ event ไม่ถูกต้อง") from None
    if kind not in EVENT_STATUS:
        raise ApiError(400, "BAD_EVENT", "ไม่รู้จักชนิด event")
    occurred = event.get("occurred_at")
    inserted = db.execute(insert(PaymentEvent).values(
        id=uuid.uuid4(), provider=provider, event_id=event_id, type=kind, outcome="received",
        payload_sha256=hashlib.sha256(body).hexdigest(),
        occurred_at=datetime.fromisoformat(occurred) if occurred else None,
    ).on_conflict_do_nothing(index_elements=["provider", "event_id"]).returning(PaymentEvent.id)).scalar()
    if inserted is None:
        return {"duplicate": True}
    record = db.get(PaymentEvent, inserted)

    payment = db.scalars(select(Payment).where(Payment.provider == provider, Payment.provider_ref == ref)
                         .with_for_update()).first()
    if payment is None:
        record.outcome = "unknown_payment"
        return {"outcome": record.outcome}
    record.payment_id = payment.id
    if (amount, currency) != (payment.amount_satang, payment.currency):
        record.outcome = "amount_mismatch"  # never grants; the amount is the server's, not the event's
        return {"outcome": record.outcome}
    target = EVENT_STATUS[kind]
    if target == "refunded" and payment.status != "succeeded":
        record.outcome = "ignored_out_of_order"  # only a paid payment can be refunded
        return {"outcome": record.outcome, "status": payment.status}
    if STATUS_ORDER[target] <= STATUS_ORDER[payment.status] and not (payment.status == "failed" and target == "succeeded"):
        record.outcome = "ignored_out_of_order"
        return {"outcome": record.outcome, "status": payment.status}
    at = now()
    sub = db.scalars(select(Subscription).where(Subscription.workspace_id == payment.workspace_id)
                     .with_for_update()).one()
    if target == "succeeded":
        payment.applied = _grant(db, sub, payment, at)
        payment.succeeded_at = at
    elif target == "refunded" and payment.status == "succeeded":
        payment.applied = _refund(db, sub, payment, at)
    payment.status, payment.updated_at = target, at
    record.outcome = "applied"
    return {"outcome": record.outcome, "status": payment.status, "applied": payment.applied}


def _grant(db: Session, sub: Subscription, payment: Payment, at: datetime) -> str:
    cycle = roll(db, sub, at)
    plan = db.get(Plan, payment.plan_id)
    if not cycle.active or sub.status == "trial":
        # Nothing paid is running: the paid cycle starts now, with a fresh quota.
        sub.plan_id, sub.status, sub.next_plan_id, sub.paid_cycles_ahead = plan.id, "active", None, 0
        sub.current_period_start, sub.current_period_end = at, at + timedelta(days=plan.interval_days)
        sub.updated_at = at
        return "started"
    sub.paid_cycles_ahead += 1  # renewal: takes over when the current cycle ends
    if plan.id != cycle.plan.id:
        sub.next_plan_id = plan.id  # plan change at the next cycle (PRD §8 MVP)
    sub.updated_at = at
    return "queued"


def _refund(db: Session, sub: Subscription, payment: Payment, at: datetime) -> str:
    """D06 (PO, 2026-10-09): no refunds in any case, so nothing here offers one. A refund can still
    arrive from the provider (e.g. a card dispute): it is recorded; money that came back takes back a
    renewal that has not started; a running cycle is left to an admin (recorded, never silently cut)."""
    roll(db, sub, at)
    if payment.applied == "queued" and sub.paid_cycles_ahead > 0:
        sub.paid_cycles_ahead -= 1
        if sub.paid_cycles_ahead == 0:
            sub.next_plan_id = None
        sub.updated_at = at
        return "removed"
    return "needs_review"


def sandbox_event(secret: bytes, payment: Payment, outcome: str) -> tuple[bytes, str]:
    """What the sandbox provider sends for `outcome` (succeeded/failed/pending/refunded), signed."""
    body = json.dumps({
        "event_id": f"evt_{secrets.token_hex(10)}", "type": f"payment.{outcome}", "provider_ref": payment.provider_ref,
        "amount": payment.amount_satang, "currency": payment.currency, "occurred_at": now().isoformat(),
    }, separators=(",", ":")).encode()
    return body, sign(secret, body)


# --- staff operations (P6.5, FR-22, E-46) -------------------------------------------------------

def snapshot(sub: Subscription) -> dict:
    return {"plan_id": str(sub.plan_id), "status": sub.status, "cycle_start": sub.current_period_start.isoformat(),
            "cycle_end": sub.current_period_end.isoformat(), "paid_cycles_ahead": sub.paid_cycles_ahead,
            "next_plan_id": str(sub.next_plan_id) if sub.next_plan_id else None}


def admin_change_plan(db: Session, sub: Subscription, plan: Plan, when: str, at: datetime) -> None:
    roll(db, sub, at)
    if when == "next_cycle":
        sub.next_plan_id = plan.id
    else:  # now: same cycle and quota period, new caps
        sub.plan_id, sub.next_plan_id = plan.id, None
    sub.updated_at = at


def admin_extend(db: Session, sub: Subscription, days: int, at: datetime) -> None:
    cycle = roll(db, sub, at)
    if not cycle.active:  # an expired subscription restarts on its plan for `days`
        sub.current_period_start, sub.current_period_end, sub.status = at, at + timedelta(days=days), "active"
    else:
        sub.current_period_end = sub.current_period_end + timedelta(days=days)
    sub.updated_at = at


def admin_end_now(db: Session, sub: Subscription, at: datetime) -> None:
    roll(db, sub, at)
    sub.current_period_end, sub.paid_cycles_ahead, sub.next_plan_id = at, 0, None
    sub.status, sub.updated_at = "expired", at


def new_plan_version(db: Session, base: Plan, changes: dict, at: datetime) -> Plan:
    """Plans are never edited in place (PRD P6.5): a change is a new version; running subscriptions
    keep the version they paid for until they renew onto the new one."""
    latest = db.scalar(select(Plan.version).where(Plan.code == base.code).order_by(Plan.version.desc()).limit(1))
    fields = {c: getattr(base, c) for c in ("code", "name", "is_demo", "max_registered_agents", "max_concurrent_sessions",
                                            "max_devices", "clips_per_month", "price_satang", "currency", "interval_days",
                                            "is_purchasable", "retention_days")}
    fields.update(changes)
    plan = Plan(version=latest + 1, created_at=at, **fields)
    db.add(plan)
    db.flush()
    return plan
