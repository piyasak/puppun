"""Platform staff: users/workspaces, jobs, payments, plans, quota and retention (P6.4/P6.5, FR-22, E-46).

- Only users with a platform role reach these routes; everyone else gets 404 (deps.staff).
- Support reads; only admin changes anything (deps.admin_only).
- Every change needs a reason (>= 10 characters) and is audited with the values before and after.
- Payment history is never deleted or rewritten here; refunds are not offered (D06: no refunds).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, billing, pilot, quota, retention
from .. import jobs as job_rules
from ..deps import StaffAuth, admin_only, get_db, staff
from ..entitlements import DEFAULT_PLAN_CODE, entitlement
from ..errors import ApiError, not_found
from ..models import AuditEvent, Device, Job, Membership, Payment, Plan, Subscription, User, Workspace

router = APIRouter(prefix="/v1/admin")


class Reason(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


class PlanChange(Reason):
    plan_code: str = Field(max_length=32)
    plan_version: int | None = None
    when: Literal["now", "next_cycle"] = "next_cycle"


class Extend(Reason):
    days: int = Field(ge=1, le=366)


class QuotaAdjust(Reason):
    units: int = Field(ge=-10_000, le=10_000)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")


class NewPlanVersion(Reason):
    price_satang: int | None = Field(default=None, ge=0)
    clips_per_month: int | None = Field(default=None, ge=0)
    unlimited_clips: bool | None = None  # True: no clip cap (stored as NULL); False with clips_per_month: a cap again
    max_registered_agents: int | None = Field(default=None, ge=0)
    max_concurrent_sessions: int | None = Field(default=None, ge=0)
    max_devices: int | None = Field(default=None, ge=0)
    retention_days: int | None = Field(default=None, ge=1, le=3650)
    is_purchasable: bool | None = None
    name: str | None = Field(default=None, max_length=100)
    interval_days: int | None = Field(default=None, ge=1, le=366)  # e.g. the trial's 5 days
    is_demo: bool | None = None  # shown as an example price ("Demo") rather than a real one


class PlanStatus(Reason):
    """Switches that change no entitlement anyone paid for, so they apply to the latest version in place."""
    selling: bool | None = None  # offered on the plans page / checkout
    demo: bool | None = None  # labelled as an example price (Demo) instead of a live price


class RetentionRun(Reason):
    dry_run: bool = True


def _workspace_out(db: Session, ws: Workspace, *, detail: bool = False, role: str = "support") -> dict:
    ent = entitlement(db, ws.id)
    owner = db.execute(select(User).join(Membership, Membership.user_id == User.id)
                       .where(Membership.workspace_id == ws.id).order_by(Membership.created_at)).scalars().first()
    out = {"id": str(ws.id), "name": ws.name, "owner": {"username": owner.username, "email": owner.email} if owner else None,
           "subscription": {"status": ent.cycle.status, "plan": f"{ent.plan.code} v{ent.plan.version}",
                            "cycle_end": ent.cycle.end.isoformat(), "paid_cycles_ahead": ent.cycle.paid_cycles_ahead}}
    if detail:
        out["quota"] = quota.summary(db, ws.id, billing.now())
        out["counts"] = {
            "jobs": db.scalar(select(func.count()).select_from(Job).where(Job.workspace_id == ws.id)),
            "devices": db.scalar(select(func.count()).select_from(Device).where(Device.workspace_id == ws.id,
                                                                                Device.unbound_at.is_(None))),
        }
        pays = db.scalars(select(Payment).where(Payment.workspace_id == ws.id).order_by(Payment.created_at.desc()).limit(20)).all()
        out["payments"] = [{"id": str(p.id), "status": p.status, "created_at": p.created_at.isoformat(),
                            **({"amount_satang": p.amount_satang, "currency": p.currency} if role == "admin" else {})}
                           for p in pays]
        events = db.scalars(select(AuditEvent).where(AuditEvent.workspace_id == ws.id)
                            .order_by(AuditEvent.created_at.desc()).limit(30)).all()
        out["audit"] = [{"action": e.action, "at": e.created_at.isoformat(), "reason": e.reason, "details": e.details}
                        for e in events]
    return out


def _workspace(db: Session, workspace_id: uuid.UUID) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise not_found()
    return ws


def _plan(db: Session, code: str, version: int | None) -> Plan:
    stmt = select(Plan).where(Plan.code == code)
    stmt = stmt.where(Plan.version == version) if version else stmt.order_by(Plan.version.desc())
    plan = db.scalars(stmt).first()
    if plan is None:
        raise ApiError(404, "PLAN_NOT_FOUND", "ไม่พบแพ็กเกจนี้")
    return plan


def _subscription(db: Session, workspace_id: uuid.UUID) -> Subscription:
    sub = db.scalars(select(Subscription).where(Subscription.workspace_id == workspace_id).with_for_update()).first()
    if sub is None:
        raise not_found()
    return sub


@router.get("/me")
def whoami(who: StaffAuth = Depends(staff)):
    return {"role": who.role}


@router.get("/workspaces")
def workspaces(q: str = "", who: StaffAuth = Depends(staff), db: Session = Depends(get_db)):
    stmt = select(Workspace).join(Membership, Membership.workspace_id == Workspace.id).join(User, User.id == Membership.user_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.username).like(like),
                              func.lower(Workspace.name).like(like)))
    rows = db.scalars(stmt.distinct().order_by(Workspace.created_at.desc()).limit(50)).all()
    return {"items": [_workspace_out(db, ws) for ws in rows]}


@router.get("/workspaces/{workspace_id}")
def workspace(workspace_id: uuid.UUID, who: StaffAuth = Depends(staff), db: Session = Depends(get_db)):
    return _workspace_out(db, _workspace(db, workspace_id), detail=True, role=who.role)


@router.post("/workspaces/{workspace_id}/plan")
def change_plan(workspace_id: uuid.UUID, body: PlanChange, request: Request, who: StaffAuth = Depends(admin_only),
                db: Session = Depends(get_db)):
    sub = _subscription(db, workspace_id)
    plan = _plan(db, body.plan_code, body.plan_version)
    before = billing.snapshot(sub)
    billing.admin_change_plan(db, sub, plan, body.when, billing.now())
    audit.record(db, request, "admin.subscription.plan", workspace_id=workspace_id, actor_user_id=who.user_id,
                 target_id=sub.id, reason=body.reason, details={"before": before, "after": billing.snapshot(sub),
                                                                "when": body.when})
    db.commit()
    return _workspace_out(db, db.get(Workspace, workspace_id), detail=True, role=who.role)


@router.post("/workspaces/{workspace_id}/extend")
def extend(workspace_id: uuid.UUID, body: Extend, request: Request, who: StaffAuth = Depends(admin_only),
           db: Session = Depends(get_db)):
    sub = _subscription(db, workspace_id)
    before = billing.snapshot(sub)
    billing.admin_extend(db, sub, body.days, billing.now())
    audit.record(db, request, "admin.subscription.extend", workspace_id=workspace_id, actor_user_id=who.user_id,
                 target_id=sub.id, reason=body.reason, details={"before": before, "after": billing.snapshot(sub),
                                                                "days": body.days})
    db.commit()
    return _workspace_out(db, db.get(Workspace, workspace_id), detail=True, role=who.role)


@router.post("/workspaces/{workspace_id}/end")
def end_now(workspace_id: uuid.UUID, body: Reason, request: Request, who: StaffAuth = Depends(admin_only),
            db: Session = Depends(get_db)):
    sub = _subscription(db, workspace_id)
    before = billing.snapshot(sub)
    billing.admin_end_now(db, sub, billing.now())
    audit.record(db, request, "admin.subscription.end", workspace_id=workspace_id, actor_user_id=who.user_id,
                 target_id=sub.id, reason=body.reason, details={"before": before, "after": billing.snapshot(sub)})
    db.commit()
    return _workspace_out(db, db.get(Workspace, workspace_id), detail=True, role=who.role)


@router.post("/workspaces/{workspace_id}/quota")
def adjust_quota(workspace_id: uuid.UUID, body: QuotaAdjust, request: Request, who: StaffAuth = Depends(admin_only),
                 db: Session = Depends(get_db)):
    if body.units == 0:
        raise ApiError(422, "VALIDATION_ERROR", "จำนวนต้องไม่เป็น 0")
    _workspace(db, workspace_id)
    before = quota.summary(db, workspace_id, billing.now())
    result = quota.adjust(db, workspace_id, body.units, body.idempotency_key, "admin_adjust")
    if result["applied"]:
        audit.record(db, request, "admin.quota.adjust", workspace_id=workspace_id, actor_user_id=who.user_id,
                     reason=body.reason, details={"before": before, "units": body.units})
    db.commit()
    return {"applied": result["applied"], "quota": quota.summary(db, workspace_id, billing.now())}


@router.get("/jobs")
def jobs(state: str | None = None, workspace_id: uuid.UUID | None = None, job_id: uuid.UUID | None = None,
         who: StaffAuth = Depends(staff), db: Session = Depends(get_db)):
    """Support looks jobs up by Job ID (FR-23); sources and errors, never clip files or tokens."""
    stmt = select(Job).order_by(Job.created_at.desc()).limit(100)
    if job_id:
        stmt = stmt.where(Job.id == job_id)
    if workspace_id:
        stmt = stmt.where(Job.workspace_id == workspace_id)
    if state:
        stmt = stmt.where(Job.state == state)
    return {"items": [{"id": str(j.id), "workspace_id": str(j.workspace_id), "state": j.state,
                       "source": j.source_url or j.source_label, "error_code": j.error_code,
                       "error_detail": j.error_detail, "planned_clips": j.planned_clips,
                       "created_at": j.created_at.isoformat()} for j in db.scalars(stmt).all()]}


@router.get("/payments")
def payments(status: str | None = None, who: StaffAuth = Depends(admin_only), db: Session = Depends(get_db)):
    stmt = select(Payment).order_by(Payment.created_at.desc()).limit(100)
    if status:
        stmt = stmt.where(Payment.status == status)
    return {"items": [{"id": str(p.id), "workspace_id": str(p.workspace_id), "status": p.status,
                       "amount_satang": p.amount_satang, "currency": p.currency, "provider": p.provider,
                       "applied": p.applied, "created_at": p.created_at.isoformat()} for p in db.scalars(stmt).all()]}


@router.get("/plans")
def plans(who: StaffAuth = Depends(staff), db: Session = Depends(get_db)):
    rows = db.scalars(select(Plan).order_by(Plan.code, Plan.version)).all()
    return {"items": [{"id": str(p.id), "code": p.code, "version": p.version, "name": p.name, "price_satang": p.price_satang,
                       "clips_per_month": p.clips_per_month, "max_registered_agents": p.max_registered_agents,
                       "max_concurrent_sessions": p.max_concurrent_sessions, "max_devices": p.max_devices,
                       "retention_days": p.retention_days, "interval_days": p.interval_days,
                       "is_purchasable": p.is_purchasable, "example": p.is_demo}
                      for p in rows]}


@router.post("/plans/{code}/versions")
def new_version(code: str, body: NewPlanVersion, request: Request, who: StaffAuth = Depends(admin_only),
                db: Session = Depends(get_db)):
    """D05 is configured here later: a new version, never an edit of one somebody paid for."""
    base = db.scalars(select(Plan).where(Plan.code == code).order_by(Plan.version.desc())).first()
    if base is None:
        raise ApiError(404, "PLAN_NOT_FOUND", "ไม่พบแพ็กเกจนี้")
    changes = body.model_dump(exclude={"reason", "unlimited_clips"}, exclude_none=True)
    if body.unlimited_clips:
        changes["clips_per_month"] = None
    if not changes:
        raise ApiError(422, "VALIDATION_ERROR", "ไม่มีค่าที่เปลี่ยน")
    plan = billing.new_plan_version(db, base, changes, billing.now())
    if changes.get("is_purchasable", base.is_purchasable):
        base.is_purchasable = False  # one purchasable version per plan
    audit.record(db, request, "admin.plan.version", actor_user_id=who.user_id, target_id=plan.id, reason=body.reason,
                 details={"code": code, "from_version": base.version, "to_version": plan.version, "changes": changes})
    db.commit()
    return {"code": plan.code, "version": plan.version}


@router.post("/plans/{code}/status")
def plan_status(code: str, body: PlanStatus, request: Request, who: StaffAuth = Depends(admin_only),
                db: Session = Depends(get_db)):
    """Open or close a plan for sale, or switch its Demo label, without a new version (PO 2026-10-10)."""
    latest = db.scalars(select(Plan).where(Plan.code == code).order_by(Plan.version.desc()).with_for_update()).first()
    if latest is None:
        raise ApiError(404, "PLAN_NOT_FOUND", "ไม่พบแพ็กเกจนี้")
    if body.selling is None and body.demo is None:
        raise ApiError(422, "VALIDATION_ERROR", "ไม่มีค่าที่เปลี่ยน")
    if code == DEFAULT_PLAN_CODE and body.selling:
        raise ApiError(422, "TRIAL_NOT_FOR_SALE", "แพ็กเกจทดลองใช้ให้ทุก Workspace ใหม่อัตโนมัติ ไม่เปิดขาย")
    before = {"selling": latest.is_purchasable, "demo": latest.is_demo}
    if body.selling is not None:
        if body.selling:  # one purchasable version per plan
            for older in db.scalars(select(Plan).where(Plan.code == code, Plan.id != latest.id)).all():
                older.is_purchasable = False
        latest.is_purchasable = body.selling
    if body.demo is not None:
        latest.is_demo = body.demo
    after = {"selling": latest.is_purchasable, "demo": latest.is_demo}
    audit.record(db, request, "admin.plan.status", actor_user_id=who.user_id, target_id=latest.id, reason=body.reason,
                 details={"code": code, "version": latest.version, "before": before, "after": after})
    db.commit()
    return {"code": code, "version": latest.version, **after}


@router.post("/jobs/{job_id}/reset")
def admin_reset_job(job_id: uuid.UUID, body: Reason, request: Request, who: StaffAuth = Depends(admin_only),
                    db: Session = Depends(get_db)):
    """Support: start a customer's job again (missing clip files, new video location), with a reason."""
    job = db.scalars(select(Job).where(Job.id == job_id).with_for_update()).first()
    if job is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบงานนี้")
    before = job.state
    mode = job_rules.reset(db, job)
    audit.record(db, request, "admin.job.reset", workspace_id=job.workspace_id, actor_user_id=who.user_id,
                 target_id=job.id, reason=body.reason, details={"mode": mode, "before": before})
    db.commit()
    return {"id": str(job.id), "state": job.state, "reset": mode}


@router.post("/retention")
def run_retention(body: RetentionRun, request: Request, who: StaffAuth = Depends(admin_only),
                  db: Session = Depends(get_db)):
    result = retention.sweep(db, request.app.state.storage, billing.now(), dry_run=body.dry_run)
    audit.record(db, request, "admin.retention", actor_user_id=who.user_id, reason=body.reason,
                 details={"deleted": len(result.deleted), "kept_in_use": len(result.kept_in_use), "dry_run": body.dry_run})
    db.commit()
    return {"deleted": result.deleted, "kept_in_use": result.kept_in_use, "dry_run": body.dry_run}


@router.get("/pilot-report")
def pilot_report(days: int = Query(default=30, ge=1, le=366), who: StaffAuth = Depends(staff),
                 db: Session = Depends(get_db)):
    """G7-01/G7-02 evidence from the server's records for the last `days` days (counts only, no amounts)."""
    until = billing.now()
    return pilot.report(db, until - timedelta(days=days), until)
