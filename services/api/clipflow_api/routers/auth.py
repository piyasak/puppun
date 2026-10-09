"""Account onboarding and /me (FR-01, G2-01).

Sign-up, sign-in, sign-out, email confirmation and password reset happen in the browser
against Supabase Auth (E-27). After the first sign-in the web app calls
`POST /v1/onboarding` once to create the application profile, the Workspace (Owner) and
the content-rights acceptance (Q-14).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit
from ..deps import WebAuth, get_db, identity, web_auth
from ..entitlements import default_plan
from ..errors import ApiError
from ..identity import Identity
from ..models import Membership, RightsAcceptance, Subscription, User, Workspace

router = APIRouter(prefix="/v1")

# Version of the content-rights declaration shown at sign-up (Q-14). Bump when the text changes.
RIGHTS_DECLARATION_VERSION = "2026-10-07"
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")


class OnboardingIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    workspace_name: str | None = Field(default=None, max_length=100)
    accept_rights: bool

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("username_invalid")
        return v


def _me(db: Session, user_id, workspace_id) -> dict:
    user = db.get(User, user_id)
    ws = db.get(Workspace, workspace_id)
    member = db.scalars(
        select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
    ).one()
    rights = db.scalars(
        select(RightsAcceptance)
        .where(RightsAcceptance.workspace_id == workspace_id)
        .order_by(RightsAcceptance.accepted_at.desc())
    ).first()
    return {
        "user": {"id": str(user.id), "email": user.email, "username": user.username,
                 "platform_role": user.platform_role},
        "workspace": {"id": str(ws.id), "name": ws.name, "timezone": ws.timezone},
        "role": member.role,
        "rights_declaration": (
            {"version": rights.declaration_version, "accepted_at": rights.accepted_at.isoformat()} if rights else None
        ),
    }


@router.post("/onboarding", status_code=201)
def onboarding(body: OnboardingIn, request: Request, who: Identity = Depends(identity), db: Session = Depends(get_db)):
    if not body.accept_rights:
        raise ApiError(422, "RIGHTS_NOT_ACCEPTED", "ต้องยอมรับคำรับรองสิทธิ์ในเนื้อหาก่อนเริ่มใช้งาน")
    if db.get(User, who.user_id) is not None:
        raise ApiError(409, "ALREADY_ONBOARDED", "บัญชีนี้ตั้งค่าเสร็จแล้ว")
    user = User(id=who.user_id, email=who.email, username=body.username)
    ws = Workspace(name=(body.workspace_name or "").strip() or f"{body.username} workspace")
    db.add_all([user, ws])
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # Two parallel onboarding calls for the same user also land here; the loser retries /me.
        if db.get(User, who.user_id) is not None:
            raise ApiError(409, "ALREADY_ONBOARDED", "บัญชีนี้ตั้งค่าเสร็จแล้ว") from None
        raise ApiError(409, "USERNAME_TAKEN", "ชื่อผู้ใช้นี้ถูกใช้แล้ว") from None
    db.add(Membership(workspace_id=ws.id, user_id=user.id, role="owner"))
    db.add(RightsAcceptance(workspace_id=ws.id, user_id=user.id, declaration_version=RIGHTS_DECLARATION_VERSION))
    # Every Workspace starts on the demo plan until billing exists (P6, D05).
    trial = default_plan(db)
    started = datetime.now(UTC)
    db.add(Subscription(workspace_id=ws.id, plan_id=trial.id, status="trial", current_period_start=started,
                        current_period_end=started + timedelta(days=trial.interval_days), paid_cycles_ahead=0))
    audit.record(db, request, "account.onboard", workspace_id=ws.id, actor_user_id=user.id, target_id=user.id)
    db.commit()
    return _me(db, user.id, ws.id)


@router.get("/me")
def me(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    return _me(db, auth.user_id, auth.workspace_id)
