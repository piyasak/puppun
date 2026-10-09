"""Plan-wide caps and Environment allocations (FR-13, PRD §F).

Every change to an Environment's limits locks the Workspace's subscription row first, so two
concurrent requests cannot both pass the sum check (the second waits and sees the first).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import billing
from .billing import Cycle
from .errors import ApiError
from .models import AgentInstallation, AgentSession, Device, Environment, Plan, Subscription

LIMITS = ("registered_agent_limit", "concurrent_session_limit", "device_limit")
PLAN_CAP = {
    "registered_agent_limit": "max_registered_agents",
    "concurrent_session_limit": "max_concurrent_sessions",
    "device_limit": "max_devices",
}
DEFAULT_PLAN_CODE = "trial"


def default_plan(db: Session) -> Plan:
    plan = db.scalars(select(Plan).where(Plan.code == DEFAULT_PLAN_CODE).order_by(Plan.version.desc())).first()
    if plan is None:
        raise RuntimeError("default plan missing; run migrations")
    return plan


@dataclass(frozen=True)
class Entitlement:
    subscription: Subscription
    plan: Plan  # the plan of the effective cycle (renewals and plan changes applied, E-45)
    cycle: Cycle

    def cap(self, limit: str) -> int:
        return getattr(self.plan, PLAN_CAP[limit])


def entitlement(db: Session, workspace_id: uuid.UUID, *, lock: bool = False) -> Entitlement:
    """With `lock`, the cycle is also rolled forward and saved (under the subscription row lock)."""
    stmt = select(Subscription).where(Subscription.workspace_id == workspace_id)
    if lock:
        stmt = stmt.with_for_update()
    sub = db.scalars(stmt).first()
    if sub is None:
        raise ApiError(403, "NO_SUBSCRIPTION", "Workspace นี้ยังไม่มีแพ็กเกจ")
    cycle = billing.roll(db, sub, billing.now()) if lock else billing.effective(db, sub, billing.now())
    return Entitlement(sub, cycle.plan, cycle)


def allocated(db: Session, workspace_id: uuid.UUID, *, exclude: uuid.UUID | None = None) -> dict[str, int]:
    cols = [func.coalesce(func.sum(getattr(Environment, name)), 0) for name in LIMITS]
    stmt = select(*cols).where(Environment.workspace_id == workspace_id)
    if exclude is not None:
        stmt = stmt.where(Environment.id != exclude)
    return dict(zip(LIMITS, (int(v) for v in db.execute(stmt).one()), strict=True))


def check_allocation(db: Session, workspace_id: uuid.UUID, requested: dict[str, int],
                     *, exclude: uuid.UUID | None = None) -> None:
    """Raise PLAN_LIMIT_EXCEEDED unless the other Environments plus `requested` fit the plan.

    Caller must hold the subscription lock (`entitlement(..., lock=True)`) in the same transaction.
    """
    ent = entitlement(db, workspace_id)
    others = allocated(db, workspace_id, exclude=exclude)
    over = [
        {"limit": name, "plan_cap": ent.cap(name), "allocated_elsewhere": others[name], "requested": requested[name]}
        for name in LIMITS
        if others[name] + requested[name] > ent.cap(name)
    ]
    if over:
        raise ApiError(409, "PLAN_LIMIT_EXCEEDED", "เกินจำนวนที่แพ็กเกจอนุญาต (รวมทุก Environment)", {"limits": over})


def in_use(db: Session, *, workspace_id: uuid.UUID | None = None, environment_id: uuid.UUID | None = None,
           at=None) -> dict[str, int]:
    """Live usage: registered installations, live sessions and bound (not unbound) devices."""
    from .agent_sessions import live_filter, now

    at = at or now()
    inst = select(func.count()).select_from(AgentInstallation).where(AgentInstallation.deregistered_at.is_(None))
    sess = select(func.count()).select_from(AgentSession).where(*live_filter(at))
    dev = select(func.count()).select_from(Device).where(Device.unbound_at.is_(None))
    if workspace_id is not None:
        inst = inst.where(AgentInstallation.workspace_id == workspace_id)
        sess = sess.where(AgentSession.workspace_id == workspace_id)
        dev = dev.where(Device.workspace_id == workspace_id)
    if environment_id is not None:
        inst = inst.where(AgentInstallation.environment_id == environment_id)
        sess = sess.where(AgentSession.environment_id == environment_id)
        dev = dev.where(Device.environment_id == environment_id)
    return {"registered_agent_limit": db.scalar(inst), "concurrent_session_limit": db.scalar(sess),
            "device_limit": db.scalar(dev)}