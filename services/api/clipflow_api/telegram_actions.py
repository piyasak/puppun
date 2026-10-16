"""Buttons on Telegram messages (Q-52 phase 1.5): act on a post from the chat, under the web's own rules.

A problem message (UNKNOWN / NEEDS_ACTION) carries buttons. Only a person who linked their own Telegram
account (a link code opened in a private chat with the bot) and is still a member of the Workspace can use
them, in the chat the message was sent to. Every press asks to confirm first. Confirming runs the same
functions as the web, at the state_version the message was made for (a post that changed since refuses),
and is audited with the punpun user and their Telegram id. Settling an UNKNOWN post needs evidence: the bot
asks, and only the person who pressed can answer by replying. Buttons expire after 24 hours.

The handlers return Bot API calls [(method, payload)] for the webhook to make after its commit.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, diagnostics, posts, schedules
from .errors import ApiError
from .models import Membership, Notification, PostingGrant, ScheduleItem, TelegramAction, TelegramChat, TelegramUser

TTL = timedelta(hours=24)
RESOLVE = ("found_published", "confirmed_not_published")
DONE_WORDS = {
    "retry": "🔁 ลองโพสต์ใหม่แล้ว (เข้าคิวรอบถัดไป)",
    "cancel": "🗑 ยกเลิกโพสต์นี้แล้ว",
    "check": "🔍 ขอตรวจหน้าจอแล้ว Agent จะส่งภาพเมื่อโทรศัพท์ว่าง ดูได้ที่หน้า โทรศัพท์ บนเว็บ",
    "found_published": "✅ บันทึกว่าโพสต์ขึ้นแล้ว",
    "confirmed_not_published": "❌ บันทึกว่าไม่ได้โพสต์ (ลองใหม่ได้จากเว็บ)",
}
Call = tuple[str, dict]
_CODE = re.compile(r"รหัส ([A-Za-z0-9]{8,24})")


def now() -> datetime:
    return datetime.now(UTC)


def buttons_for(item: ScheduleItem) -> list[list[tuple[str, str]]]:
    """Rows of (action, label) for a post that needs a person; [] when nothing can be done from a chat."""
    if item.state == "UNKNOWN":
        return [[("found_published", "✅ พบโพสต์แล้ว"), ("confirmed_not_published", "❌ ไม่ได้โพสต์")],
                [("check", "🔍 ตรวจหน้าจอ")]]
    if item.state == "NEEDS_ACTION":
        first = [("retry", "🔁 ลองใหม่")] if item.reason in posts.RETRYABLE_REASONS else []
        return [first + [("cancel", "🗑 ยกเลิกโพสต์นี้")], [("check", "🔍 ตรวจหน้าจอ")]]
    return []


def attach(db: Session, note: Notification, item: ScheduleItem, rows: list[list[tuple[str, str]]]) -> None:
    """Make one action per button for this message (per chat), bound to the post's current state_version."""
    out = []
    for row in rows:
        line = []
        for action, label in row:
            token = secrets.token_urlsafe(12).replace("-", "a").replace("_", "b")[:16]
            db.add(TelegramAction(workspace_id=note.workspace_id, notification_id=note.id, chat_ref=note.chat_ref,
                                  token=token, action=action, label=label, item_id=item.id, device_id=item.device_id,
                                  state_version=item.state_version, expires_at=now() + TTL))
            line.append([label, token])
        out.append(line)
    note.buttons = out


def keyboard(buttons: list | None) -> dict:
    return {"inline_keyboard": [[{"text": label, "callback_data": f"a:{token}"} for label, token in row]
                                for row in (buttons or [])]}


def _person(db: Session, workspace_id: uuid.UUID, telegram_user_id: int | None) -> TelegramUser | None:
    """The presser's own linked account, if they are still a member of this Workspace."""
    if telegram_user_id is None:
        return None
    person = db.scalars(select(TelegramUser).where(TelegramUser.workspace_id == workspace_id,
                                                   TelegramUser.telegram_user_id == telegram_user_id,
                                                   TelegramUser.unlinked_at.is_(None))).first()
    if person is None:
        return None
    member = db.scalars(select(Membership).where(Membership.workspace_id == workspace_id,
                                                 Membership.user_id == person.user_id)).first()
    return person if member is not None else None


def _check_for(db: Session, item: ScheduleItem) -> str:
    if item.state != "UNKNOWN":
        return "profile"
    grant = db.get(PostingGrant, item.grant_id) if item.grant_id else None
    return "newest_public_video" if grant is not None and grant.visibility == "everyone" else "newest_private_video"


def _run(db: Session, act: TelegramAction, person: TelegramUser, evidence: str | None = None) -> str:
    """The action itself, with the web's rules. Raises ApiError; the caller keeps it in a savepoint."""
    item = db.scalars(select(ScheduleItem).where(ScheduleItem.id == act.item_id,
                                                 ScheduleItem.workspace_id == act.workspace_id)
                      .with_for_update()).first()
    if item is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบโพสต์นี้แล้ว")
    if act.action == "retry":
        posts.retry(db, item, act.state_version)
    elif act.action == "cancel":
        if item.state_version != act.state_version:
            raise ApiError(409, "VERSION_CONFLICT", "รายการถูกเปลี่ยนไปแล้ว", {"current_version": item.state_version})
        schedules.cancel_item(item)
    elif act.action == "check":
        diagnostics.request(db, act.workspace_id, item.device_id, _check_for(db, item), person.user_id)
    elif act.action in RESOLVE:
        if len((evidence or "").strip()) < 5:  # the person's own words; the Telegram name added below does not count
            raise ApiError(422, "EVIDENCE_REQUIRED", "ต้องระบุหลักฐาน เช่น ลิงก์โพสต์ หรือสิ่งที่ตรวจในแอป TikTok "
                                                     "(ตอบกลับข้อความของบอทอีกครั้ง)")
        posts.resolve(db, item, decision=act.action, evidence=f"{evidence or ''} (Telegram: {person.name})"[:500],
                      actor=person.user_id, expected_state_version=act.state_version)
    else:
        raise ApiError(422, "VALIDATION_ERROR", "ไม่รู้จักปุ่มนี้")
    audit.record(db, None, f"telegram.{act.action}", workspace_id=act.workspace_id, actor_user_id=person.user_id,
                 target_id=item.id, details={"telegram_user_id": person.telegram_user_id,
                                             "state_version": act.state_version, "via": "telegram"})
    return DONE_WORDS[act.action]


def _finish(db: Session, act: TelegramAction, person: TelegramUser, chat_id: int, message_id: int | None,
            evidence: str | None = None) -> list[Call]:
    try:
        with db.begin_nested():
            done = _run(db, act, person, evidence)
    except ApiError as exc:
        return [("sendMessage", {"chat_id": chat_id, "text": f"ทำไม่ได้: {exc.message}\nดูและแก้ที่เว็บ"})]
    act.used_at, act.used_by, act.result = now(), person.user_id, done[:300]
    calls: list[Call] = [("sendMessage", {"chat_id": chat_id, "text": f"{done}\nโดย {person.name}"})]
    if message_id is not None:  # the post moved on: the other buttons on that message are spent too
        calls.append(("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id,
                                                 "reply_markup": {"inline_keyboard": []}}))
    return calls


def on_press(db: Session, cq: dict) -> list[Call]:
    """A button press: a:<token> asks to confirm, c:<token> confirms, x:<token> goes back."""
    kind, _, token = str(cq.get("data", "")).partition(":")
    message = cq.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")

    def answer(text: str, alert: bool = False) -> Call:
        return ("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": text[:190], "show_alert": alert})

    act = db.scalars(select(TelegramAction).where(TelegramAction.token == token).with_for_update()).first()
    chat = db.get(TelegramChat, act.chat_ref) if act is not None else None
    if kind not in ("a", "c", "x") or act is None or chat is None or chat.unlinked_at is not None or chat.chat_id != chat_id:
        return [answer("ปุ่มนี้ใช้ไม่ได้แล้ว")]
    person = _person(db, act.workspace_id, (cq.get("from") or {}).get("id"))
    if person is None:
        return [answer("กดได้เฉพาะคนใน Workspace ที่เชื่อม Telegram ส่วนตัวแล้ว: หน้า การแจ้งเตือน > เชื่อม Telegram "
                       "แล้วเปิดลิงก์ในแชตส่วนตัวกับบอท", alert=True)]
    if act.used_at is not None:
        return [answer(f"ทำไปแล้ว: {act.result}")]
    if act.expires_at <= now():
        return [answer("ปุ่มหมดอายุแล้ว (24 ชั่วโมง) ดูและแก้ที่เว็บ", alert=True)]
    note = db.get(Notification, act.notification_id)
    edit = {"chat_id": chat_id, "message_id": message_id}
    if kind == "a":
        confirm = {"inline_keyboard": [[{"text": f"ยืนยัน: {act.label}", "callback_data": f"c:{act.token}"}],
                                       [{"text": "↩️ ไม่ทำ", "callback_data": f"x:{act.token}"}]]}
        return [answer("กดยืนยันอีกครั้ง"), ("editMessageReplyMarkup", edit | {"reply_markup": confirm})]
    if kind == "x":
        return [answer("ไม่ทำแล้ว"), ("editMessageReplyMarkup", edit | {"reply_markup": keyboard(note.buttons if note else [])})]
    if act.action in RESOLVE:  # evidence first, from the same person, as a reply
        act.prompt_telegram_user_id = person.telegram_user_id
        ask = (f"{act.label}: ตอบกลับ (Reply) ข้อความนี้ด้วยหลักฐาน เช่น ลิงก์โพสต์ หรือสิ่งที่เห็นในแอป TikTok "
               f"(อย่างน้อย 5 ตัวอักษร) • รหัส {act.token}")
        return [answer("พิมพ์หลักฐานโดยตอบกลับข้อความของบอท"),
                ("editMessageReplyMarkup", edit | {"reply_markup": keyboard(note.buttons if note else [])}),
                ("sendMessage", {"chat_id": chat_id, "text": ask,
                                 "reply_markup": {"force_reply": True, "selective": True}})]
    return [answer("กำลังทำ"), *_finish(db, act, person, chat_id, message_id)]


def on_reply(db: Session, message: dict) -> list[Call]:
    """A reply to the bot's evidence question: settles the UNKNOWN post with that text as evidence."""
    asked = message.get("reply_to_message") or {}
    found = _CODE.search(asked.get("text") or "")
    if not found or not (asked.get("from") or {}).get("is_bot"):
        return []
    chat_id = (message.get("chat") or {}).get("id")
    act = db.scalars(select(TelegramAction).where(TelegramAction.token == found.group(1)).with_for_update()).first()
    chat = db.get(TelegramChat, act.chat_ref) if act is not None else None
    sender = (message.get("from") or {}).get("id")
    if (act is None or act.action not in RESOLVE or chat is None or chat.unlinked_at is not None
            or chat.chat_id != chat_id or act.prompt_telegram_user_id != sender):
        return []  # not the person who pressed: ignored
    if act.used_at is not None or act.expires_at <= now():
        return [("sendMessage", {"chat_id": chat_id, "text": "ปุ่มนี้ใช้ไปแล้วหรือหมดอายุ ดูและแก้ที่เว็บ"})]
    person = _person(db, act.workspace_id, sender)
    if person is None:
        return []
    return _finish(db, act, person, chat_id, None, evidence=(message.get("text") or "").strip())
