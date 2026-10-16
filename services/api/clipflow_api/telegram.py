"""Telegram for notifications (Q-52, PO 2026-10-16): the Bot API, linking a chat, and the updates it sends.

One punpun bot; its token is a server setting (TELEGRAM_BOT_TOKEN) and is never sent to Agents, browsers,
logs or messages. A Workspace owner links a chat (private or group) from the web: the server makes a
one-time code (stored as SHA-256, 15 minutes), the owner opens t.me/<bot>?start=<code> and presses Start,
Telegram sends us "/start <code>" (webhook, checked with TELEGRAM_WEBHOOK_SECRET) and the chat is linked.
Phase 1 only sends; buttons that act (resolve, retry) are phase 1.5.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import NotifyRule, TelegramChat, TelegramLinkCode

API = "https://api.telegram.org"
CODE_TTL = timedelta(minutes=15)
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class TelegramError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def now() -> datetime:
    return datetime.now(UTC)


def call(token: str, method: str, payload: dict, timeout: float = 10.0) -> dict:
    """One Bot API call. The token is only in the URL path of this request, never logged."""
    if not token:
        raise TelegramError("no bot token")
    req = urllib.request.Request(f"{API}/bot{token}/{method}", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _direct.open(req, timeout=timeout) as resp:
            answer = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read() or b"{}").get("description", "")
        except ValueError:
            detail = ""
        raise TelegramError(f"{exc.code} {detail}"[:200], exc.code) from None
    except (OSError, ValueError) as exc:
        raise TelegramError(type(exc).__name__) from None
    if not answer.get("ok"):
        raise TelegramError(str(answer.get("description", "not ok"))[:200])
    return answer.get("result") or {}


def send(token: str, chat_id: int, text: str) -> None:
    call(token, "sendMessage", {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True})


def set_webhook(token: str, url: str, secret: str) -> None:
    call(token, "setWebhook", {"url": url, "secret_token": secret, "allowed_updates": ["message", "my_chat_member"]})


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def new_link_code(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> tuple[str, datetime]:
    code = secrets.token_urlsafe(18).replace("-", "a").replace("_", "b")[:24]
    expires = now() + CODE_TTL
    db.add(TelegramLinkCode(workspace_id=workspace_id, code_hash=_hash(code), created_by=user_id, expires_at=expires))
    return code, expires


def deep_link(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start={code}"


def _chat_title(chat: dict) -> str:
    title = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
    return (title or chat.get("username") or str(chat.get("id")))[:200]


def handle_update(db: Session, update: dict) -> tuple[int, str] | None:
    """Apply one update. Returns (chat_id, reply) when the bot should answer, else None."""
    member = update.get("my_chat_member")
    if member:  # the bot was removed from a group / blocked: stop sending there
        status = (member.get("new_chat_member") or {}).get("status")
        if status in ("left", "kicked"):
            for chat in db.scalars(select(TelegramChat).where(TelegramChat.chat_id == member["chat"]["id"],
                                                              TelegramChat.unlinked_at.is_(None))).all():
                chat.unlinked_at = now()
        return None
    message = update.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    if not text.startswith("/start") or "id" not in chat:
        return None
    parts = text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if not code:
        return chat["id"], "สวัสดี นี่คือบอทแจ้งเตือนของ punpun\nเชื่อมแชตนี้จากเว็บ: หน้า การแจ้งเตือน > เชื่อม Telegram"
    row = db.scalars(select(TelegramLinkCode).where(TelegramLinkCode.code_hash == _hash(code))
                     .with_for_update()).first()
    if row is None or row.used_at is not None or row.expires_at <= now():
        return chat["id"], "รหัสเชื่อมต่อไม่ถูกต้องหรือหมดอายุ ขอรหัสใหม่จากหน้า การแจ้งเตือน บนเว็บ"
    row.used_at = now()
    linked = db.scalars(select(TelegramChat).where(TelegramChat.workspace_id == row.workspace_id,
                                                   TelegramChat.chat_id == chat["id"])).first()
    if linked is None:
        linked = TelegramChat(workspace_id=row.workspace_id, chat_id=chat["id"], title=_chat_title(chat),
                              kind=str(chat.get("type", "private"))[:16], linked_by=row.created_by)
        db.add(linked)
        db.flush()
    else:
        linked.unlinked_at, linked.title = None, _chat_title(chat)
    if not db.scalars(select(NotifyRule).where(NotifyRule.chat_ref == linked.id)).first():
        db.add(NotifyRule(workspace_id=row.workspace_id, chat_ref=linked.id, device_id=None))  # every phone
    return chat["id"], ("เชื่อมแชตนี้กับ punpun แล้ว ✅\nจะได้รับแจ้งเตือนการโพสต์ ปัญหาที่ต้องให้คนดู สถานะระบบ "
                        "และสรุปรายวัน ปรับได้ที่หน้า การแจ้งเตือน บนเว็บ")
