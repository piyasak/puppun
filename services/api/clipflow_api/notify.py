"""Telegram notifications (Q-52, PO 2026-10-16): what is said, to which chat, and when.

Kinds, each switched on per chat and per phone in `notify_rules` (device_id NULL = every phone):
- posting: a post verified; batched, one message per chat at most every BATCH_EVERY;
- problems: a post needs a person (UNKNOWN / NEEDS_ACTION): at once;
- health: an Agent offline, a phone not ready, a posting grant nearly used up or about to end: at once,
  once per incident (dedupe keys);
- summary: per phone at `summary_hour` (Asia/Bangkok): today's posts, followers/likes and the newest
  videos' views from what the Agent read on Profile (account_stats), and what is scheduled next.

Messages go through the `notifications` outbox (unique per chat + dedupe key, so an event is never sent
twice) and are sent by `tick`, run every LOOP_S by one server (Postgres advisory lock). A notification never
changes what happens to a post: every hook swallows its own errors.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from . import telegram, telegram_actions
from .models import (
    AccountStat,
    AgentInstallation,
    ClipMetadata,
    Device,
    Notification,
    NotifyRule,
    PostingGrant,
    ScheduleItem,
    TelegramChat,
)

log = logging.getLogger("clipflow.notify")
TZ = ZoneInfo("Asia/Bangkok")
BATCH_EVERY = timedelta(hours=1)
AGENT_OFFLINE = timedelta(minutes=10)
MAX_ATTEMPTS = 5
LOOP_S = 30
LOCK_KEY = 5202610  # pg advisory lock: one sender
WEBHOOK_CHECK_S = 600
PROBLEM_WORDS = {
    "UNKNOWN": "ไม่แน่ใจว่าโพสต์ขึ้นหรือไม่ ต้องให้คนตรวจในโทรศัพท์",
    "NEEDS_ACTION": "หยุดก่อนโพสต์ ต้องให้คนดู",
}


def now() -> datetime:
    return datetime.now(UTC)


def phone_label(device: Device) -> str:
    name = device.display_name or device.model or device.serial
    return f"{name} (@{device.expected_account})" if device.expected_account else name


def _rules(db: Session, workspace_id: uuid.UUID, device_id: uuid.UUID | None, kind: str) -> list[NotifyRule]:
    q = select(NotifyRule).join(TelegramChat, TelegramChat.id == NotifyRule.chat_ref).where(
        NotifyRule.workspace_id == workspace_id, TelegramChat.unlinked_at.is_(None),
        getattr(NotifyRule, kind).is_(True))
    if device_id is not None:
        q = q.where(or_(NotifyRule.device_id.is_(None), NotifyRule.device_id == device_id))
    return list(db.scalars(q).all())


def enqueue(db: Session, workspace_id: uuid.UUID, device_id: uuid.UUID | None, kind: str, body: str, key: str,
            *, batch: bool = False, item: ScheduleItem | None = None) -> int:
    """One outbox row per chat whose rules want `kind` for this phone; repeated keys are ignored."""
    chats = {r.chat_ref for r in _rules(db, workspace_id, device_id, kind)}
    added = 0
    for chat_ref in chats:
        exists = db.scalar(select(func.count()).select_from(Notification).where(
            Notification.chat_ref == chat_ref, Notification.dedupe_key == key))
        if exists:
            continue
        note = Notification(workspace_id=workspace_id, chat_ref=chat_ref, kind=kind, dedupe_key=key[:120],
                            text=body[:4000], batch=batch)
        db.add(note)
        rows = telegram_actions.buttons_for(item) if item is not None and not batch else []
        if rows:  # phase 1.5: act from the chat
            db.flush()
            telegram_actions.attach(db, note, item, rows)
        added += 1
    return added


def _caption(db: Session, item: ScheduleItem) -> str:
    meta = db.scalars(select(ClipMetadata).where(ClipMetadata.clip_id == item.clip_id,
                                                 ClipMetadata.version == item.metadata_version)).first()
    caption = (meta.caption if meta else "") or ""
    return caption if len(caption) <= 60 else caption[:57] + "..."


def _web(settings, path: str) -> str:
    return settings.web_origin.rstrip("/") + path if settings is not None else path


def on_post_event(db: Session, item: ScheduleItem, settings=None) -> None:
    """Called after a post's state changed; never raises (a notification must not change a post)."""
    try:
        with db.begin_nested():
            device = db.get(Device, item.device_id)
            if device is None:
                return
            local = datetime.now(TZ).strftime("%H:%M")
            if item.state == "VERIFIED_SUCCESS" and (item.posting_mode or "") == "live":
                enqueue(db, item.workspace_id, device.id, "posting",
                        f"✅ {local} {phone_label(device)}: {_caption(db, item)}", f"posted:{item.id}", batch=True)
            elif item.state in PROBLEM_WORDS:
                enqueue(db, item.workspace_id, device.id, "problems",
                        f"⚠️ {phone_label(device)}: {PROBLEM_WORDS[item.state]}\n"
                        f"เหตุผล: {item.reason or '-'}\nโพสต์: {_caption(db, item)}\n"
                        f"ดูและแก้ที่เว็บ: {_web(settings, '/schedules')}",
                        f"problem:{item.id}:{item.state_version}", item=item)
    except Exception:  # noqa: BLE001
        log.exception("notify: post event %s", item.id)


# --- health ------------------------------------------------------------------------------------------------

def health_checks(db: Session, at: datetime, settings=None) -> None:
    ws_ids = set(db.scalars(select(NotifyRule.workspace_id).where(NotifyRule.health.is_(True))).all())
    for ws in ws_ids:
        for inst in db.scalars(select(AgentInstallation).where(
                AgentInstallation.workspace_id == ws, AgentInstallation.deregistered_at.is_(None),
                AgentInstallation.last_seen_at.is_not(None),
                AgentInstallation.last_seen_at < at - AGENT_OFFLINE,
                AgentInstallation.last_seen_at > at - timedelta(days=2))).all():
            seen = inst.last_seen_at.astimezone(TZ).strftime("%d/%m %H:%M")
            enqueue(db, ws, None, "health",
                    f"📴 Agent ออฟไลน์ (เห็นล่าสุด {seen}) โพสต์ของโทรศัพท์ที่ต่อกับเครื่องนั้นจะรอจนกว่า Agent กลับมา",
                    f"agent_offline:{inst.id}:{inst.last_seen_at.isoformat()}")
        for device in db.scalars(select(Device).where(Device.workspace_id == ws, Device.unbound_at.is_(None),
                                                      Device.last_state.in_(("missing", "offline", "unauthorized")))).all():
            day = at.astimezone(TZ).strftime("%Y-%m-%d")
            words = {"missing": "ไม่ได้ต่อกับเครื่อง", "offline": "ออฟไลน์", "unauthorized": "ยังไม่อนุญาต USB debugging"}
            enqueue(db, ws, device.id, "health", f"📱 {phone_label(device)}: {words[device.last_state]}",
                    f"phone:{device.id}:{device.last_state}:{day}")
        for grant in db.scalars(select(PostingGrant).where(PostingGrant.workspace_id == ws,
                                                           PostingGrant.revoked_at.is_(None),
                                                           PostingGrant.expires_at > at)).all():
            left = grant.max_posts - grant.used_posts
            if left <= max(3, grant.max_posts // 10):
                enqueue(db, ws, None, "health",
                        f"🎫 สิทธิ์โพสต์จริงของ @{grant.account} เหลือ {left}/{grant.max_posts} ครั้ง",
                        f"grant_low:{grant.id}")
            if grant.expires_at <= at + timedelta(hours=24):
                enqueue(db, ws, None, "health",
                        f"🎫 สิทธิ์โพสต์จริงของ @{grant.account} หมดอายุ {grant.expires_at.astimezone(TZ):%d/%m %H:%M}",
                        f"grant_expiring:{grant.id}")


# --- daily summary -----------------------------------------------------------------------------------------

def _fmt(n: int | None) -> str:
    return "-" if n is None else f"{n:,}"


def _delta(new: int | None, old: int | None) -> str:
    if new is None or old is None:
        return ""
    d = new - old
    return f" ({'+' if d >= 0 else ''}{d:,})"


def summary_text(db: Session, device: Device, at: datetime) -> str:
    start = datetime.combine(at.astimezone(TZ).date(), datetime.min.time(), TZ).astimezone(UTC)
    items = db.scalars(select(ScheduleItem).where(ScheduleItem.device_id == device.id,
                                                  ScheduleItem.updated_at >= start)).all()
    posted = sum(1 for i in items if i.state == "VERIFIED_SUCCESS" and (i.posting_mode or "") == "live")
    problems = sum(1 for i in items if i.state in ("UNKNOWN", "NEEDS_ACTION"))
    upcoming = db.scalar(select(func.count()).select_from(ScheduleItem).where(
        ScheduleItem.device_id == device.id, ScheduleItem.state == "SCHEDULED",
        ScheduleItem.scheduled_at < at + timedelta(hours=24))) or 0
    latest = db.scalars(select(AccountStat).where(AccountStat.device_id == device.id)
                        .order_by(AccountStat.captured_at.desc()).limit(1)).first()
    lines = [f"📊 สรุปวันนี้ {at.astimezone(TZ):%d/%m} • {phone_label(device)}",
             f"โพสต์สำเร็จ {posted} • ต้องให้คนดู {problems} • คิว 24 ชม.ข้างหน้า {upcoming}"]
    if latest is not None:
        before = db.scalars(select(AccountStat).where(AccountStat.device_id == device.id,
                                                      AccountStat.captured_at <= latest.captured_at - timedelta(hours=20))
                            .order_by(AccountStat.captured_at.desc()).limit(1)).first()
        views = [v for v in (latest.video_views or []) if isinstance(v, int)]
        lines.append(f"ผู้ติดตาม {_fmt(latest.followers)}{_delta(latest.followers, before.followers if before else None)}"
                     f" • ถูกใจ {_fmt(latest.likes)}{_delta(latest.likes, before.likes if before else None)}")
        if views:
            lines.append(f"ยอดดูวิดีโอล่าสุด {len(views)} คลิป รวม {sum(views):,} • สูงสุด {max(views):,}")
        lines.append(f"(อ่านจากโปรไฟล์เมื่อ {latest.captured_at.astimezone(TZ):%d/%m %H:%M})")
    else:
        lines.append("ยังไม่มียอดผู้ติดตาม/ยอดดู (Agent 0.9.0 ขึ้นไปจะอ่านจากโปรไฟล์ให้วันละ 2 ครั้ง)")
    return "\n".join(lines)


def summaries(db: Session, at: datetime) -> None:
    local = at.astimezone(TZ)
    for rule in db.scalars(select(NotifyRule).join(TelegramChat, TelegramChat.id == NotifyRule.chat_ref).where(
            NotifyRule.summary.is_(True), NotifyRule.summary_hour == local.hour,
            TelegramChat.unlinked_at.is_(None))).all():
        q = select(Device).where(Device.workspace_id == rule.workspace_id, Device.unbound_at.is_(None))
        if rule.device_id is not None:
            q = q.where(Device.id == rule.device_id)
        for device in db.scalars(q).all():
            key = f"summary:{rule.id}:{device.id}:{local:%Y-%m-%d}"
            if db.scalar(select(func.count()).select_from(Notification).where(
                    Notification.chat_ref == rule.chat_ref, Notification.dedupe_key == key)):
                continue
            db.add(Notification(workspace_id=rule.workspace_id, chat_ref=rule.chat_ref, kind="summary",
                                dedupe_key=key, text=summary_text(db, device, at)))


# --- sending ----------------------------------------------------------------------------------------------

def _deliver(db: Session, token: str, chat: TelegramChat, rows: list[Notification], body: str, at: datetime,
             buttons: list | None = None) -> None:
    try:
        telegram.send(token, chat.chat_id, body, telegram_actions.keyboard(buttons) if buttons else None)
        for r in rows:
            r.sent_at, r.attempts = at, r.attempts + 1
    except telegram.TelegramError as exc:
        for r in rows:
            r.attempts, r.last_error = r.attempts + 1, str(exc)[:300]
        if exc.status == 403 or (exc.status == 400 and "chat not found" in str(exc).lower()):
            chat.unlinked_at = at  # blocked or removed: stop trying this chat


def send_pending(db: Session, token: str, at: datetime) -> None:
    if not token:
        return
    pending = db.scalars(select(Notification).where(Notification.sent_at.is_(None), Notification.attempts < MAX_ATTEMPTS)
                         .order_by(Notification.created_at).limit(100).with_for_update(skip_locked=True)).all()
    by_chat: dict[uuid.UUID, list[Notification]] = {}
    for row in pending:
        by_chat.setdefault(row.chat_ref, []).append(row)
    for chat_ref, rows in by_chat.items():
        chat = db.get(TelegramChat, chat_ref)
        if chat is None or chat.unlinked_at is not None:
            for r in rows:
                r.attempts, r.last_error = MAX_ATTEMPTS, "chat unlinked"
            continue
        singles = [r for r in rows if not r.batch]
        for r in singles:
            _deliver(db, token, chat, [r], r.text, at, r.buttons)
        batched = [r for r in rows if r.batch]
        if batched and min(r.created_at for r in batched) <= at - BATCH_EVERY:
            body = f"✅ โพสต์สำเร็จ {len(batched)} รายการ\n" + "\n".join(r.text.removeprefix("✅ ") for r in batched)
            _deliver(db, token, chat, batched, body, at)


def tick(db: Session, settings, at: datetime | None = None) -> None:
    """One round: health checks, daily summaries, then send what is due."""
    at = at or now()
    health_checks(db, at, settings)
    summaries(db, at)
    db.flush()
    send_pending(db, settings.telegram_bot_token, at)


def start_loop(app) -> None:
    """The background sender (one per process; only the one holding the advisory lock works)."""
    settings = app.state.settings
    if not settings.telegram_bot_token or not settings.notify_loop:
        return

    def run() -> None:
        checked = 0.0
        while True:
            if time.monotonic() - checked >= WEBHOOK_CHECK_S:  # registered on start, then checked every 10 min
                app.state.telegram_webhook = telegram.ensure_webhook(settings, force=checked == 0.0)
                if app.state.telegram_webhook["error"]:
                    log.warning("telegram webhook: %s", app.state.telegram_webhook["error"])
                checked = time.monotonic()
            try:
                with app.state.db.sessionmaker() as db:
                    if db.scalar(text("select pg_try_advisory_xact_lock(:k)"), {"k": LOCK_KEY}):
                        tick(db, settings)
                    db.commit()
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("notify loop")
            time.sleep(LOOP_S)

    threading.Thread(target=run, name="clipflow-notify", daemon=True).start()

