"""Authorized real posting (Q-42).

A platform admin grants one Workspace one TikTok account up to N real posts until a date, with a
reason (audited, revocable). Everything else stays a dry run:

- claim: a post is handed out live only when the Agent says it can post live, the phone has an
  expected account, and a grant for that account is valid with room left after the live posts
  already handed out (`for_claim`). Otherwise it goes out as a dry run, as before.
- SUBMITTING: the grant row is locked and checked again (`use`); one use is counted there, before
  the Agent presses Post, so a crash after Post can never lead to an extra post.

No env value, setting or CLI command creates a grant.

Q-48 (PO 2026-10-13): a platform admin can turn the account check off for a Workspace (`account_check`).
Then a grant of that Workspace covers any account (the phone's account is neither required nor compared),
but only for Agents that say they can post without the check (0.5.7+); older Agents keep the old rules.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .errors import ApiError
from .models import PostingGrant, ScheduleItem, Workspace

HANDLE_RE = re.compile(r"^@?[A-Za-z0-9._]{2,24}$")
# Q-49 (PO 2026-10-15): "everyone" (public) too, only to Agents that say they can post publicly (0.5.8+).
VISIBILITIES = ("only_me", "everyone")
# Handed out live but not yet at SUBMITTING: these may still use the grant.
PENDING_LIVE = ("CLAIMED", "TRANSFERRING", "PREPARING")


ANY_ACCOUNT = "*"  # Q-48: a grant for any account of the Workspace; it is used only while the account check is off


def normalize_account(raw: str) -> str:
    value = (raw or "").strip()
    if value in ("", ANY_ACCOUNT):
        return ANY_ACCOUNT
    if not HANDLE_RE.match(value):
        raise ApiError(422, "VALIDATION_ERROR", "ชื่อบัญชี TikTok ไม่ถูกต้อง", {"field": "account"})
    return value.lstrip("@").lower()


def status(grant: PostingGrant, at: datetime) -> str:
    if grant.revoked_at is not None:
        return "revoked"
    if grant.expires_at <= at:
        return "expired"
    if grant.used_posts >= grant.max_posts:
        return "used_up"
    return "active"


def out(grant: PostingGrant, at: datetime) -> dict:
    return {
        "id": str(grant.id), "account": grant.account, "visibility": grant.visibility,
        "max_posts": grant.max_posts, "used_posts": grant.used_posts,
        "remaining": max(grant.max_posts - grant.used_posts, 0), "expires_at": grant.expires_at.isoformat(),
        "reason": grant.reason, "created_at": grant.created_at.isoformat() if grant.created_at else None,
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None, "status": status(grant, at),
    }


def create(db: Session, workspace_id: uuid.UUID, *, account: str, max_posts: int, expires_at: datetime,
           visibility: str, reason: str, actor: uuid.UUID, at: datetime) -> PostingGrant:
    if visibility not in VISIBILITIES:
        raise ApiError(422, "VISIBILITY_NOT_AVAILABLE", "เปิดได้เฉพาะโพสต์แบบ \"เฉพาะฉัน\" หรือ \"ทุกคน\"")
    if expires_at <= at:
        raise ApiError(422, "VALIDATION_ERROR", "วันหมดอายุต้องอยู่ในอนาคต", {"field": "expires_at"})
    grant = PostingGrant(workspace_id=workspace_id, account=normalize_account(account), visibility=visibility,
                         max_posts=max_posts, used_posts=0, expires_at=expires_at, reason=reason, created_by=actor)
    db.add(grant)
    db.flush()
    return grant


def revoke(grant: PostingGrant, actor: uuid.UUID, at: datetime) -> None:
    if grant.revoked_at is None:
        grant.revoked_at, grant.revoked_by = at, actor


def _pending(db: Session, grant_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(ScheduleItem).where(
        ScheduleItem.grant_id == grant_id, ScheduleItem.grant_used.is_(False),
        ScheduleItem.state.in_(PENDING_LIVE))) or 0


def account_check(db: Session, workspace_id: uuid.UUID) -> bool:
    ws = db.get(Workspace, workspace_id)
    return True if ws is None else bool(ws.account_check)


def for_claim(db: Session, workspace_id: uuid.UUID, account: str | None, at: datetime, *,
              any_account: bool = False, public_ok: bool = True) -> PostingGrant | None:
    """The grant a post on this account may go out live under, or None (a dry run). `any_account`
    (Q-48, account check off): any grant of the Workspace, whatever the phone's account, but the phone's own
    account's grants first, then "*" (any account), then other accounts' (PO 2026-10-15: with the check off,
    tx1's post used tx2's older "only you" grant instead of tx1's own public one).
    Within those, the oldest valid grant with room is used first; the row is locked so two claims count the same room."""
    if not account and not any_account:
        return None
    where = [PostingGrant.workspace_id == workspace_id]
    if not public_ok:  # an Agent that cannot post publicly never gets a public grant
        where.append(PostingGrant.visibility == "only_me")
    if not any_account:
        where.append(PostingGrant.account == account.lower())
    grants = db.scalars(select(PostingGrant).where(
        *where, PostingGrant.revoked_at.is_(None), PostingGrant.expires_at > at,
        PostingGrant.used_posts < PostingGrant.max_posts).order_by(PostingGrant.created_at)
        .with_for_update()).all()
    own = (account or "").lower().lstrip("@")
    rank = {own: 0, ANY_ACCOUNT: 1} if own else {ANY_ACCOUNT: 1}
    for grant in sorted(grants, key=lambda g: rank.get(g.account, 2)):  # stable: oldest first within a rank
        if grant.used_posts + _pending(db, grant.id) < grant.max_posts:
            return grant
    return None


def use(db: Session, item: ScheduleItem, account: str | None, at: datetime) -> str | None:
    """Count one use for this post at SUBMITTING. Returns a refusal reason, or None when Post may be pressed."""
    if item.grant_used:
        return None  # a repeated SUBMITTING with a new event id: already counted
    grant = db.scalars(select(PostingGrant).where(PostingGrant.id == item.grant_id).with_for_update()).first()
    if grant is None or grant.workspace_id != item.workspace_id:
        return "POSTING_GRANT_MISSING"
    if account_check(db, item.workspace_id) and (account or "").lower() != grant.account:
        return "POSTING_GRANT_ACCOUNT"  # the phone's account was changed after the claim
    state = status(grant, at)
    if state != "active":
        return {"revoked": "POSTING_GRANT_REVOKED", "expired": "POSTING_GRANT_EXPIRED"}.get(state, "POSTING_GRANT_USED_UP")
    grant.used_posts += 1
    item.grant_used = True
    return None


def expected_mode(db: Session, workspace_id: uuid.UUID, account: str | None, at: datetime, server_mode: str) -> str:
    """What the customer should expect for a post on this account now (the claim decides for real:
    the Agent must also be 0.4.0+ and the grant may be used up by then)."""
    if server_mode == "live":
        return "live"
    any_account = not account_check(db, workspace_id)
    return "live" if for_claim(db, workspace_id, account, at, any_account=any_account) is not None else "dry_run"
