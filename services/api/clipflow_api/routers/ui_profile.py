"""TikTok UI profile (Q-50): admins edit it, Agents read the latest."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from .. import ui_profile as rules
from ..agent_sessions import AgentContext
from ..deps import StaffAuth, admin_only, get_db, staff
from ..errors import ApiError
from ..models import UiProfile
from .agent import agent_context

admin_router = APIRouter(prefix="/v1/admin/ui-profile")
agent_router = APIRouter(prefix="/v1/agent/ui-profile")


class ProfileIn(BaseModel):
    body: dict
    reason: str = Field(min_length=10, max_length=500)


def _out(row: UiProfile) -> dict:
    return {"version": row.version, "body": row.body, "reason": row.reason,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def latest(db: Session) -> UiProfile | None:
    return db.scalars(select(UiProfile).order_by(UiProfile.version.desc()).limit(1)).first()


@admin_router.get("")
def show(who: StaffAuth = Depends(staff), db: Session = Depends(get_db)):
    """The profile in use, the built-in defaults and what can be set, and the last versions."""
    rows = db.scalars(select(UiProfile).order_by(UiProfile.version.desc()).limit(20)).all()
    return {"current": _out(rows[0]) if rows else None, "defaults": rules.DEFAULTS,
            "spec": {k: list(v) for k, v in rules.SPEC.items()}, "history": [_out(r) for r in rows]}


@admin_router.post("", status_code=201)
def save(body: ProfileIn, request: Request, who: StaffAuth = Depends(admin_only), db: Session = Depends(get_db)):
    """A new version (admin only, with a reason, audited). Only the settings that differ from the defaults
    need to be given; anything not in the spec, or out of its limits, is refused whole."""
    try:
        rules.validate(body.body)
    except rules.ProfileError as exc:
        raise ApiError(422, "UI_PROFILE_INVALID", f"ค่าหน้าจอ TikTok ไม่ถูกต้อง: {exc}", {"problems": str(exc)}) from None
    version = (db.scalar(select(func.max(UiProfile.version))) or 0) + 1
    row = UiProfile(version=version, body=body.body, reason=body.reason, created_by=who.user_id)
    db.add(row)
    db.flush()
    audit.record(db, request, "admin.ui_profile.save", actor_user_id=who.user_id, target_id=row.id,
                 reason=body.reason, details={"version": version, "body": body.body})
    db.commit()
    return _out(row)


@agent_router.get("")
def for_agent(ctx: AgentContext = Depends(agent_context), db: Session = Depends(get_db)):
    row = latest(db)
    if row is None:
        raise ApiError(404, "NOT_FOUND", "ยังไม่มีค่าหน้าจอ TikTok (Agent ใช้ค่าในตัว)")
    return {"version": row.version, "body": row.body}
