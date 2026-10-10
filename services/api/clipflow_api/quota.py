"""Quota ledger in integer clip units (FR-21, G3-04, PRD §F).

- reserve: when the Agent has validated the source and the real clip count is known (E-04).
- settle: one unit per delivered clip, keyed by (job, clip index).
- release: whatever is still held when a job completes short, fails or is cancelled.

Every entry carries a unique idempotency key and is inserted with ON CONFLICT DO NOTHING, so
a redelivered event or a double click can never charge or refund twice (T10). Reservations
take the Workspace's subscription row lock, so two jobs cannot both spend the last units (T21).
Periods are subscription cycles: the key is the cycle's start date in Asia/Bangkok (E-45, was
calendar months, Q-04). A new cycle therefore starts a fresh quota exactly once.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .entitlements import entitlement
from .models import QuotaLedger

TZ = ZoneInfo("Asia/Bangkok")


def _add(db: Session, workspace_id, job_id, period: str, entry: str, units: int, key: str, reason: str | None) -> bool:
    """Insert one ledger entry; False when the key already exists (a repeat)."""
    stmt = insert(QuotaLedger).values(
        id=uuid.uuid4(), workspace_id=workspace_id, job_id=job_id, period=period, entry=entry, units=units,
        idempotency_key=key, reason=reason,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(QuotaLedger.id)
    # RETURNING, not rowcount: rowcount is not reliable for this statement (found by test_admin, 2026-10-09).
    return db.execute(stmt).scalar() is not None


def used(db: Session, workspace_id, period: str) -> int:
    signed = case((QuotaLedger.entry == "reserve", QuotaLedger.units),
                  (QuotaLedger.entry == "release", -QuotaLedger.units),
                  (QuotaLedger.entry == "deduct", QuotaLedger.units), else_=0)  # staff deduction counts as used
    return int(db.scalar(select(func.coalesce(func.sum(signed), 0)).where(
        QuotaLedger.workspace_id == workspace_id, QuotaLedger.period == period)))


def granted(db: Session, workspace_id, period: str) -> int:
    """Extra units staff added to this cycle (E-46). Kept apart so "used" is always real usage."""
    return int(db.scalar(select(func.coalesce(func.sum(QuotaLedger.units), 0)).where(
        QuotaLedger.workspace_id == workspace_id, QuotaLedger.period == period, QuotaLedger.entry == "grant")))


def job_balance(db: Session, job_id) -> dict[str, int]:
    rows = db.execute(select(QuotaLedger.entry, func.sum(QuotaLedger.units))
                      .where(QuotaLedger.job_id == job_id).group_by(QuotaLedger.entry)).all()
    sums = {entry: int(total) for entry, total in rows}
    reserved, settled, released = sums.get("reserve", 0), sums.get("settle", 0), sums.get("release", 0)
    return {"reserved": reserved, "settled": settled, "released": released,
            "outstanding": reserved - settled - released}


def summary(db: Session, workspace_id, at: datetime) -> dict:
    ent = entitlement(db, workspace_id)
    period, bonus = ent.cycle.key, granted(db, workspace_id, ent.cycle.key)
    u = used(db, workspace_id, period)
    if ent.plan.clips_per_month is None:  # unlimited plan: usage is still recorded, nothing is capped
        return {"period": period, "limit": None, "used": u, "available": None, "unlimited": True, "granted": bonus,
                "cycle_end": ent.cycle.end.isoformat(), "status": ent.cycle.status}
    limit = ent.plan.clips_per_month + bonus
    return {"period": period, "limit": limit, "used": u, "available": max(0, limit - u), "unlimited": False,
            "granted": bonus,
            "cycle_end": ent.cycle.end.isoformat(), "status": ent.cycle.status}


class QuotaExceeded(Exception):
    def __init__(self, available: int):
        self.available = available


def reserve(db: Session, workspace_id, job_id, units: int, at: datetime) -> str:
    """Hold `units` for a job. Raises QuotaExceeded. Returns the period charged."""
    ent = entitlement(db, workspace_id, lock=True)  # serializes reservations per Workspace (T21)
    period = ent.cycle.key
    if ent.plan.clips_per_month is not None:  # unlimited plans still record the reservation below
        available = ent.plan.clips_per_month + granted(db, workspace_id, period) - used(db, workspace_id, period)
        if units > available:
            raise QuotaExceeded(max(0, available))
    _add(db, workspace_id, job_id, period, "reserve", units, f"reserve:{job_id}", "job_reserve")
    return period


def settle_clip(db: Session, workspace_id, job_id, period: str, clip_index: int) -> bool:
    return _add(db, workspace_id, job_id, period, "settle", 1, f"settle:{job_id}:{clip_index}", "clip_delivered")


def release_outstanding(db: Session, workspace_id, job_id, period: str | None, reason: str) -> int:
    """Return every unit still held by the job. Safe to call repeatedly; the caller holds the job lock."""
    if period is None:
        return 0
    outstanding = job_balance(db, job_id)["outstanding"]
    if outstanding <= 0:
        return 0
    return outstanding if _add(db, workspace_id, job_id, period, "release", outstanding,
                               f"release:{job_id}", reason) else 0


def adjust(db: Session, workspace_id, units: int, key: str, reason: str) -> dict:
    """Staff adjustment in the current cycle: +units gives back, -units takes. Idempotent by `key`."""
    ent = entitlement(db, workspace_id, lock=True)
    period = ent.cycle.key
    entry = "grant" if units > 0 else "deduct"
    added = _add(db, workspace_id, None, period, entry, abs(units), f"adjust:{key}", reason[:40])
    return {"applied": added, "period": period, "entry": entry, "units": abs(units)}
