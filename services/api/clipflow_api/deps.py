"""Request dependencies: DB session and browser identity (Supabase access token)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .errors import ApiError
from .identity import Identity, InvalidToken
from .models import Membership, User


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


def unauthenticated() -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", "กรุณาเข้าสู่ระบบ")


def identity(request: Request) -> Identity:
    """Supabase access token from `Authorization: Bearer`. Never read from cookies or the query string.

    A bearer header is not sent automatically by the browser, so cross-site requests
    cannot ride on it and no CSRF token is needed (E-27). Agent tokens are rejected here
    because they are not Supabase-signed JWTs.
    """
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthenticated()
    try:
        return request.app.state.verifier.verify(token.strip())
    except InvalidToken:
        raise unauthenticated() from None


@dataclass(frozen=True)
class WebAuth:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: str


def web_auth(who: Identity = Depends(identity), db: Session = Depends(get_db)) -> WebAuth:
    """Signed-in user with a Workspace. Users who have not onboarded get ONBOARDING_REQUIRED."""
    user = db.get(User, who.user_id)
    if user is None:
        raise ApiError(403, "ONBOARDING_REQUIRED", "กรุณาตั้งค่าบัญชีและ Workspace ให้เสร็จก่อน")
    if user.email != who.email:
        db.execute(update(User).where(User.id == user.id).values(email=who.email))
        db.commit()
    member = db.scalars(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.created_at)
    ).first()
    if member is None:
        raise ApiError(403, "ONBOARDING_REQUIRED", "กรุณาตั้งค่าบัญชีและ Workspace ให้เสร็จก่อน")
    return WebAuth(user.id, member.workspace_id, member.role)
