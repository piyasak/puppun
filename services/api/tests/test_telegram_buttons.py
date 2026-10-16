"""Telegram buttons (Q-52 phase 1.5): only linked members press, every press is confirmed, the web's rules apply."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from api_test_shop import schedule
from sqlalchemy import select, update
from test_notifications import hook, link

from clipflow_api import notify
from clipflow_api.models import (
    AuditEvent,
    Diagnostic,
    Notification,
    ScheduleItem,
    TelegramAction,
    TelegramUser,
)


def new_chat() -> int:
    return 960_000_000 + uuid.uuid4().int % 1_000_000


def problem(app, shop, state, reason):
    """One post moved to `state` and its problem message queued (as the post event would)."""
    series = schedule(shop, clips=1)
    item_id = uuid.UUID(series["items"][0]["id"])
    with app.state.db.sessionmaker() as db:
        item = db.get(ScheduleItem, item_id)
        item.state, item.reason, item.state_version = state, reason, item.state_version + 1
        notify.on_post_event(db, item, app.state.settings)
        db.commit()
        note = db.scalars(select(Notification).where(Notification.dedupe_key == f"problem:{item.id}:{item.state_version}")).one()
        tokens = {a.action: a.token for a in db.scalars(select(TelegramAction).where(TelegramAction.notification_id == note.id))}
    return item_id, note, tokens


def press(client, chat_id, data, user_id, message_id=77):
    return hook(client, {"update_id": 5, "callback_query": {
        "id": "cb1", "data": data, "from": {"id": user_id, "first_name": "PO"},
        "message": {"message_id": message_id, "chat": {"id": chat_id, "type": "private"}}}})


def reply(client, chat_id, user_id, text, asked):
    return hook(client, {"update_id": 6, "message": {
        "message_id": 90, "text": text, "from": {"id": user_id, "first_name": "PO"}, "chat": {"id": chat_id, "type": "private"},
        "reply_to_message": {"message_id": 89, "text": asked, "from": {"id": 1, "is_bot": True}}}})


def calls(bot, method):
    return [p for m, p in bot if m == method]


def state(app, item_id):
    with app.state.db.sessionmaker() as db:
        item = db.get(ScheduleItem, item_id)
        return item.state, item.reason


def test_a_private_link_links_the_person_a_group_link_does_not(shop, client, bot, app):
    group = -new_chat()
    url = shop.acc.post("/v1/notifications/telegram/link").json()["link"]
    hook(client, {"update_id": 1, "message": {"text": f"/start {url.split('start=')[1]}", "from": {"id": 5551},
                                              "chat": {"id": group, "type": "group", "title": "ทีม"}}})
    assert shop.acc.get("/v1/notifications").json()["people"] == []
    chat_id = new_chat()
    link(shop, client, chat_id)  # private: the chat id is the person's id
    people = shop.acc.get("/v1/notifications").json()["people"]
    assert [(p["name"], p["me"]) for p in people] == [("PO", True)]
    assert "กดปุ่ม" in calls(bot, "sendMessage")[-1]["text"]


def test_retry_needs_a_linked_member_and_a_confirm(shop, client, bot, app):
    chat_id = new_chat()
    link(shop, client, chat_id)
    item_id, note, tokens = problem(app, shop, "NEEDS_ACTION", "UNKNOWN_SCREEN")
    assert set(tokens) == {"retry", "cancel", "check"}

    bot.clear()
    with app.state.db.sessionmaker() as db:
        notify.send_pending(db, "123:test", datetime.now(UTC))
        db.commit()
    sent = [p for p in calls(bot, "sendMessage") if p["chat_id"] == chat_id][0]
    labels = [b["text"] for row in sent["reply_markup"]["inline_keyboard"] for b in row]
    assert labels == ["🔁 ลองใหม่", "🗑 ยกเลิกโพสต์นี้", "🔍 ตรวจหน้าจอ"]

    # A stranger, or a member who never linked their own Telegram: refused, nothing changes.
    press(client, chat_id, f"c:{tokens['retry']}", 4242)
    assert calls(bot, "answerCallbackQuery")[-1]["show_alert"] and state(app, item_id)[0] == "NEEDS_ACTION"
    # Wrong chat: refused.
    press(client, chat_id + 1, f"c:{tokens['retry']}", chat_id)
    assert "ใช้ไม่ได้" in calls(bot, "answerCallbackQuery")[-1]["text"]

    press(client, chat_id, f"a:{tokens['retry']}", chat_id)  # asks first
    confirm = calls(bot, "editMessageReplyMarkup")[-1]["reply_markup"]["inline_keyboard"]
    assert confirm[0][0]["callback_data"] == f"c:{tokens['retry']}" and state(app, item_id)[0] == "NEEDS_ACTION"
    press(client, chat_id, f"x:{tokens['retry']}", chat_id)  # back to the buttons
    assert len(calls(bot, "editMessageReplyMarkup")[-1]["reply_markup"]["inline_keyboard"]) == 2

    press(client, chat_id, f"c:{tokens['retry']}", chat_id)
    assert state(app, item_id) == ("SCHEDULED", "RETRY_REQUESTED")
    assert "ลองโพสต์ใหม่แล้ว" in calls(bot, "sendMessage")[-1]["text"]
    assert calls(bot, "editMessageReplyMarkup")[-1]["reply_markup"] == {"inline_keyboard": []}
    with app.state.db.sessionmaker() as db:
        ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "telegram.retry",
                                                 AuditEvent.target_id == item_id)).one()
        assert ev.details["telegram_user_id"] == chat_id and ev.actor_user_id == shop.acc.user_id

    press(client, chat_id, f"c:{tokens['retry']}", chat_id)  # once only
    assert "ทำไปแล้ว" in calls(bot, "answerCallbackQuery")[-1]["text"]
    press(client, chat_id, f"c:{tokens['cancel']}", chat_id)  # the post moved on: the other buttons refuse
    assert "ทำไม่ได้" in calls(bot, "sendMessage")[-1]["text"] and state(app, item_id)[0] == "SCHEDULED"


def test_an_unknown_post_is_settled_only_with_the_pressers_evidence(shop, client, bot, app):
    chat_id = new_chat()
    link(shop, client, chat_id)
    item_id, note, tokens = problem(app, shop, "UNKNOWN", "AGENT_LOST_AFTER_SUBMIT")
    assert set(tokens) == {"found_published", "confirmed_not_published", "check"}

    press(client, chat_id, f"c:{tokens['found_published']}", chat_id)
    asked = calls(bot, "sendMessage")[-1]
    assert asked["reply_markup"]["force_reply"] and tokens["found_published"] in asked["text"]
    assert state(app, item_id)[0] == "UNKNOWN"  # nothing yet

    n = len(bot)
    reply(client, chat_id, 4242, "https://www.tiktok.com/@handle0/video/1", asked["text"])  # someone else: ignored
    assert len(bot) == n and state(app, item_id)[0] == "UNKNOWN"
    reply(client, chat_id, chat_id, "ok", asked["text"])  # too short: the name added later does not count
    assert "หลักฐาน" in calls(bot, "sendMessage")[-1]["text"] and state(app, item_id)[0] == "UNKNOWN"
    reply(client, chat_id, chat_id, "เห็นในแอป โพสต์ขึ้นแล้ว", asked["text"])
    assert state(app, item_id)[0] == "VERIFIED_SUCCESS"
    with app.state.db.sessionmaker() as db:
        item = db.get(ScheduleItem, item_id)
        assert "เห็นในแอป โพสต์ขึ้นแล้ว (Telegram: PO)" in str(item.evidence)
        assert db.scalars(select(AuditEvent).where(AuditEvent.action == "telegram.found_published",
                                                   AuditEvent.target_id == item_id)).one()


def test_check_asks_the_agent_for_a_screen_and_expiry_and_unlinking_stop_buttons(shop, client, bot, app):
    chat_id = new_chat()
    link(shop, client, chat_id)
    item_id, note, tokens = problem(app, shop, "UNKNOWN", "AGENT_LOST_AFTER_SUBMIT")
    press(client, chat_id, f"c:{tokens['check']}", chat_id)
    with app.state.db.sessionmaker() as db:
        diag = db.scalars(select(Diagnostic).where(Diagnostic.device_id == uuid.UUID(shop.devices[0]))).one()
        assert diag.check == "newest_private_video" and diag.requested_by == shop.acc.user_id  # no public grant

        db.execute(update(TelegramAction).where(TelegramAction.token == tokens["confirmed_not_published"])
                   .values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
        db.commit()
    press(client, chat_id, f"c:{tokens['confirmed_not_published']}", chat_id)
    assert "หมดอายุ" in calls(bot, "answerCallbackQuery")[-1]["text"]

    person = shop.acc.get("/v1/notifications").json()["people"][0]["id"]
    assert shop.acc.client.delete(f"/v1/notifications/telegram/people/{person}", headers=shop.acc.headers()).status_code == 200
    press(client, chat_id, f"c:{tokens['found_published']}", chat_id)
    assert calls(bot, "answerCallbackQuery")[-1]["show_alert"] and state(app, item_id)[0] == "UNKNOWN"
    with app.state.db.sessionmaker() as db:
        assert db.scalars(select(TelegramUser).where(TelegramUser.id == uuid.UUID(person))).one().unlinked_at


def test_another_workspace_cannot_use_or_unlink_anything(shop, client, bot, app, onboard):
    chat_id = new_chat()
    link(shop, client, chat_id)
    person = shop.acc.get("/v1/notifications").json()["people"][0]["id"]
    other = onboard()
    assert other.client.delete(f"/v1/notifications/telegram/people/{person}", headers=other.headers()).status_code == 404
    assert other.get("/v1/notifications").json()["people"] == []
