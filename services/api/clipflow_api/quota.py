"""Quota ledger in integer clip units (FR-21, G3-04, PRD §F).

- reserve: when the Agent has validated the source and the real clip count is known (E-04).
- settle: one unit per delivered clip, keyed by (job, clip index).
- release: whatever is still held when a job completes short, fails or is cancelled.

Every entry carries a unique idempotency key and is inserted with ON CONFLICT DO NOTHING, so
a redelivered event or a double click can never charge or refund twice (T10). Reservations
take the Workspace's subscription row lock, so two jobs cannot both spend the last units (T21).
Periods are calendar months in Asia/Bangkok (Q-04).
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


def period_of(at: datetime) -> str:
    return at.astimezone(TZ).strftime("%Y-%m")


def _add(db: Session, workspace_id, job_id, period: str, entry: str, units: int, key: str, reason: str | None) -> bool:
    """Insert one ledger entry; False when the key already exists (a repeat)."""
    stmt = insert(QuotaLedger).values(
        id=uuid.uuid4(), workspace_id=workspace_id, job_id=job_id, period=period, entry=entry, units=units,
        idempotency_key=key, reason=reason,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"])
    return (db.execute(stmt).rowcount or 0) == 1


def used(db: Session, workspace_id, period: str) -> int:
    signed = case((QuotaLedger.entry == "reserve", QuotaLedger.units),
                  (QuotaLedger.entry == "release", -QuotaLedger.units), else_=0)
    return int(db.scalar(select(func.coalesce(func.sum(signed), 0)).where(
        QuotaLedger.workspace_id == workspace_id, QuotaLedger.period == period)))


def job_balance(db: Session, job_id) -> dict[str, int]:
    rows = db.execute(select(QuotaLedger.entry, func.sum(QuotaLedger.units))
                      .where(QuotaLedger.job_id == job_id).group_by(QuotaLedger.entry)).all()
    sums = {entry: int(total) for entry, total in rows}
    reserved, settled, released = sums.get("reserve", 0), sums.get("settle", 0), sums.get("release", 0)
    return {"reserved": reserved, "settled": settled, "released": released,
            "outstanding": reserved - settled - released}


def summary(db: Session, workspace_id, at: datetime) -> dict:
    period = period_of(at)
    limit = entitlement(db, workspace_id).plan.clips_per_month
    u = used(db, workspace_id, period)
    return {"period": period, "limit": limit, "used": u, "available": max(0, limit - u)}


class QuotaExceeded(Exception):
    def __init__(self, available: int):
        self.available = available


def reserve(db: Session, workspace_id, job_id, units: int, at: datetime) -> str:
    """Hold `units` for a job. Raises QuotaExceeded. Returns the period charged."""
    ent = entitlement(db, workspace_id, lock=True)  # serializes reservations per Workspace (T21)
    period = period_of(at)
    available = ent.plan.clips_per_month - used(db, workspace_id, period)
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
