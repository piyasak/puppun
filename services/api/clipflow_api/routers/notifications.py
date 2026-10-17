"""Telegram notifications (Q-52): the owner's settings page, Telegram's webhook, and the Agent's account numbers."""

from __future__ import annotations

import contextlib
import hmac
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, notify, telegram
from .. import devices as device_rules
from ..agent_sessions import AgentContext
from ..deps import WebAuth, get_db, web_auth
from ..errors import ApiError
from ..models import AccountStat, Device, Notification, NotifyRule, TelegramChat, TelegramUser
from .agent import agent_context

web_router = APIRouter(prefix="/v1/notifications")
hook_router = APIRouter(prefix="/v1/telegram")
agent_router = APIRouter(prefix="/v1/agent/account-stats")


def _chat(db: Session, auth: WebAuth, chat_ref: uuid.UUID) -> TelegramChat:
    chat = db.scalars(select(TelegramChat).where(TelegramChat.id == chat_ref, TelegramChat.workspace_id == auth.workspace_id,
                                                 TelegramChat.unlinked_at.is_(None))).first()
    if chat is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบแชตนี้")
    return chat


def _rule_out(r: NotifyRule) -> dict:
    return {"id": str(r.id), "chat_ref": str(r.chat_ref), "device_id": str(r.device_id) if r.device_id else None,
            "posting": r.posting, "problems": r.problems, "health": r.health, "summary": r.summary,
            "summary_hour": r.summary_hour}


@web_router.get("")
def overview(request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    settings = request.app.state.settings
    chats = db.scalars(select(TelegramChat).where(TelegramChat.workspace_id == auth.workspace_id,
                                                  TelegramChat.unlinked_at.is_(None)).order_by(TelegramChat.created_at)).all()
    rules = db.scalars(select(NotifyRule).where(NotifyRule.workspace_id == auth.workspace_id)
                       .order_by(NotifyRule.created_at)).all()
    phones = db.scalars(select(Device).where(Device.workspace_id == auth.workspace_id, Device.unbound_at.is_(None))).all()
    people = db.scalars(select(TelegramUser).where(TelegramUser.workspace_id == auth.workspace_id,
                                                   TelegramUser.unlinked_at.is_(None)).order_by(TelegramUser.created_at)).all()
    return {"configured": bool(settings.telegram_bot_token and settings.telegram_bot_username),
            # Whether Telegram can reach us (checked every 10 minutes by the notify loop); None before the first check
            "webhook": getattr(request.app.state, "telegram_webhook", None),
            "bot_username": settings.telegram_bot_username or None,
            "chats": [{"id": str(c.id), "title": c.title, "kind": c.kind, "created_at": c.created_at.isoformat()} for c in chats],
            "rules": [_rule_out(r) for r in rules if r.chat_ref in {c.id for c in chats}],
            "phones": [{"id": str(d.id), "label": notify.phone_label(d)} for d in phones],
            # Phase 1.5: people who can press buttons (their own Telegram, linked in a private chat)
            "people": [{"id": str(p.id), "name": p.name, "me": p.user_id == auth.user_id,
                        "created_at": p.created_at.isoformat()} for p in people]}


@web_router.post("/telegram/link", status_code=201)
def link(request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    settings = request.app.state.settings
    if not (settings.telegram_bot_token and settings.telegram_bot_username):
        raise ApiError(409, "TELEGRAM_NOT_CONFIGURED", "ระบบยังไม่ได้ตั้งค่าบอท Telegram")
    code, expires = telegram.new_link_code(db, auth.workspace_id, auth.user_id)
    audit.record(db, request, "telegram.link_code", workspace_id=auth.workspace_id, actor_user_id=auth.user_id)
    db.commit()
    return {"link": telegram.deep_link(settings.telegram_bot_username, code), "expires_at": expires.isoformat()}


@web_router.delete("/telegram/chats/{chat_ref}")
def unlink(chat_ref: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    chat = _chat(db, auth, chat_ref)
    chat.unlinked_at = datetime.now(UTC)
    audit.record(db, request, "telegram.unlink", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=chat.id)
    db.commit()
    return {"unlinked": True}


@web_router.delete("/telegram/people/{person_id}")
def unlink_person(person_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth),
                  db: Session = Depends(get_db)):
    """That Telegram account can no longer press buttons (messages still arrive in linked chats)."""
    person = db.scalars(select(TelegramUser).where(TelegramUser.id == person_id, TelegramUser.workspace_id == auth.workspace_id,
                                                   TelegramUser.unlinked_at.is_(None))).first()
    if person is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบบัญชี Telegram นี้")
    person.unlinked_at = datetime.now(UTC)
    audit.record(db, request, "telegram.person_unlink", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=person.id)
    db.commit()
    return {"unlinked": True}


class RuleIn(BaseModel):
    chat_ref: uuid.UUID
    device_id: uuid.UUID | None = None
    posting: bool = True
    problems: bool = True
    health: bool = True
    summary: bool = True
    summary_hour: int = Field(default=21, ge=0, le=23)


@web_router.post("/rules", status_code=201)
def save_rule(body: RuleIn, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    """One rule per chat + phone (no phone = every phone): created or replaced."""
    chat = _chat(db, auth, body.chat_ref)
    if body.device_id is not None and db.scalars(select(Device).where(
            Device.id == body.device_id, Device.workspace_id == auth.workspace_id)).first() is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบโทรศัพท์นี้")
    rule = db.scalars(select(NotifyRule).where(NotifyRule.chat_ref == chat.id, NotifyRule.device_id.is_(None)
                                               if body.device_id is None else NotifyRule.device_id == body.device_id)).first()
    if rule is None:
        rule = NotifyRule(workspace_id=auth.workspace_id, chat_ref=chat.id, device_id=body.device_id)
        db.add(rule)
    for field in ("posting", "problems", "health", "summary", "summary_hour"):
        setattr(rule, field, getattr(body, field))
    db.flush()
    audit.record(db, request, "notify.rule", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                 target_id=rule.id, details=_rule_out(rule))
    db.commit()
    return _rule_out(rule)


@web_router.delete("/rules/{rule_id}")
def delete_rule(rule_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    rule = db.scalars(select(NotifyRule).where(NotifyRule.id == rule_id, NotifyRule.workspace_id == auth.workspace_id)).first()
    if rule is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบการตั้งค่านี้")
    db.delete(rule)
    db.commit()
    return {"deleted": True}


class TestIn(BaseModel):
    chat_ref: uuid.UUID


@web_router.post("/test", status_code=201)
def test_message(body: TestIn, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    chat = _chat(db, auth, body.chat_ref)
    db.add(Notification(workspace_id=auth.workspace_id, chat_ref=chat.id, kind="test", dedupe_key=f"test:{uuid.uuid4()}",
                        text="🔔 ทดสอบการแจ้งเตือนจาก punpun: แชตนี้รับข้อความได้"))
    db.commit()
    return {"queued": True}


@web_router.get("/stats")
def stats(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    """The latest numbers the Agent read per phone (followers, likes, newest videos' views)."""
    out = []
    for device in db.scalars(select(Device).where(Device.workspace_id == auth.workspace_id, Device.unbound_at.is_(None))).all():
        row = db.scalars(select(AccountStat).where(AccountStat.device_id == device.id)
                         .order_by(AccountStat.captured_at.desc()).limit(1)).first()
        out.append({"device_id": str(device.id), "label": notify.phone_label(device),
                    "stat": None if row is None else {"account": row.account, "followers": row.followers,
                                                      "following": row.following, "likes": row.likes,
                                                      "video_views": row.video_views,
                                                      "captured_at": row.captured_at.isoformat()}})
    return {"items": out}


# --- Telegram -> us ---------------------------------------------------------------------------------------

@hook_router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not settings.telegram_webhook_secret or not hmac.compare_digest(secret, settings.telegram_webhook_secret):
        raise ApiError(404, "NOT_FOUND", "Not found")
    try:
        update = await request.json()
    except ValueError:
        return {"ok": True}
    calls = telegram.handle_update(db, update if isinstance(update, dict) else {})
    db.commit()
    for method, payload in calls if settings.telegram_bot_token else []:
        with contextlib.suppress(telegram.TelegramError):
            telegram.call(settings.telegram_bot_token, method, payload)
    return {"ok": True}


# --- Agent -> us ------------------------------------------------------------------------------------------

class StatIn(BaseModel):
    serial: str = Field(max_length=64)
    account: str | None = Field(default=None, max_length=64)
    followers: int | None = Field(default=None, ge=0)
    following: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    video_views: list[int] = Field(default_factory=list, max_length=30)


@agent_router.post("", status_code=201)
def account_stat(body: StatIn, ctx: AgentContext = Depends(agent_context), db: Session = Depends(get_db)):
    key = device_rules.normalize_serial(body.serial)[1]
    device = db.scalars(select(Device).where(Device.environment_id == ctx.environment_id, Device.serial_key == key,
                                             Device.unbound_at.is_(None))).first()
    if device is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบโทรศัพท์นี้ใน Environment นี้")
    db.add(AccountStat(workspace_id=device.workspace_id, device_id=device.id, account=body.account,
                       followers=body.followers, following=body.following, likes=body.likes,
                       video_views=[v for v in body.video_views if v >= 0], captured_at=datetime.now(UTC)))
    db.commit()
    return {"saved": True}
