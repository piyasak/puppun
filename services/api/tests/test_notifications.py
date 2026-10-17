"""Telegram notifications (Q-52, PO 2026-10-16): link a chat, rules per phone, the outbox, account numbers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from api_test_shop import schedule
from conftest import TELEGRAM_SECRET as SECRET  # the "bot" fixture is in conftest
from sqlalchemy import select

from clipflow_api import notify, telegram
from clipflow_api.models import AccountStat, Device, Notification, NotifyRule, ScheduleItem, TelegramChat


def hook(client, update, secret=SECRET):
    return client.post("/v1/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": secret})


def start(chat_id, text, kind="private"):
    return {"update_id": 1, "message": {"text": text, "from": {"id": chat_id, "first_name": "PO"},
                                        "chat": {"id": chat_id, "type": kind, "first_name": "PO"}}}


def link(shop, client, chat_id):
    url = shop.acc.post("/v1/notifications/telegram/link").json()["link"]
    code = url.split("start=")[1]
    assert hook(client, start(chat_id, f"/start {code}")).status_code == 200
    return code


def delete(acc, path):
    return acc.client.delete(path, headers=acc.headers())


def test_not_configured_says_so(shop):
    got = shop.acc.get("/v1/notifications").json()
    assert got["configured"] is False and got["chats"] == []
    assert shop.acc.post("/v1/notifications/telegram/link").json()["code"] == "TELEGRAM_NOT_CONFIGURED"


def test_webhook_needs_the_secret(shop, client, bot):
    assert hook(client, start(1, "/start x"), secret="wrong").status_code == 404
    assert client.post("/v1/telegram/webhook", json={}).status_code == 404
    assert bot == []


def test_a_code_links_one_chat_once_with_a_default_rule(shop, client, bot, onboard):
    chat_id = 900_000_000 + uuid.uuid4().int % 1_000_000
    code = link(shop, client, chat_id)
    assert bot[-1][0] == "sendMessage" and "เชื่อมแชตนี้" in bot[-1][1]["text"]
    got = shop.acc.get("/v1/notifications").json()
    assert got["configured"] and got["bot_username"] == "punpun_test_bot"
    assert [c["title"] for c in got["chats"]] == ["PO"]
    assert [(r["device_id"], r["posting"], r["summary_hour"]) for r in got["rules"]] == [(None, True, 21)]

    # Used once; another chat cannot reuse it, and nothing is linked from a bad code.
    hook(client, start(chat_id + 1, f"/start {code}"))
    assert "ไม่ถูกต้อง" in bot[-1][1]["text"]
    assert len(shop.acc.get("/v1/notifications").json()["chats"]) == 1
    # Another Workspace sees none of it.
    assert onboard().get("/v1/notifications").json()["chats"] == []


def test_rules_per_phone_and_cross_tenant_404(shop, client, bot, onboard):
    link(shop, client, 910_000_000 + uuid.uuid4().int % 1_000_000)
    chat = shop.acc.get("/v1/notifications").json()["chats"][0]["id"]
    dev = shop.devices[0]
    saved = shop.acc.post("/v1/notifications/rules", json={"chat_ref": chat, "device_id": dev, "posting": False,
                                                           "problems": True, "health": False, "summary": True,
                                                           "summary_hour": 8})
    assert saved.status_code == 201 and saved.json()["summary_hour"] == 8
    again = shop.acc.post("/v1/notifications/rules", json={"chat_ref": chat, "device_id": dev, "summary_hour": 9}).json()
    assert again["id"] == saved.json()["id"] and again["posting"] is True  # replaced, not added
    assert len(shop.acc.get("/v1/notifications").json()["rules"]) == 2
    assert shop.acc.post("/v1/notifications/rules", json={"chat_ref": chat, "summary_hour": 24}).status_code == 422

    other = onboard()
    missing = str(uuid.uuid4())
    for body in ({"chat_ref": chat}, {"chat_ref": missing}):
        assert other.post("/v1/notifications/rules", json=body).json()["code"] == "NOT_FOUND"
        assert other.post("/v1/notifications/test", json=body).json()["code"] == "NOT_FOUND"
    assert shop.acc.post("/v1/notifications/rules", json={"chat_ref": chat, "device_id": missing}).status_code == 404
    assert delete(other, f"/v1/notifications/rules/{again['id']}").status_code == 404
    assert delete(other, f"/v1/notifications/telegram/chats/{chat}").status_code == 404

    assert shop.acc.post("/v1/notifications/test", json={"chat_ref": chat}).status_code == 201
    assert delete(shop.acc, f"/v1/notifications/rules/{again['id']}").status_code == 200
    assert delete(shop.acc, f"/v1/notifications/telegram/chats/{chat}").status_code == 200
    assert shop.acc.get("/v1/notifications").json()["chats"] == []


def test_post_events_queue_problems_at_once_and_successes_hourly(shop, client, bot, app):
    chat_id = 920_000_000 + uuid.uuid4().int % 1_000_000
    link(shop, client, chat_id)
    series = schedule(shop, clips=2)
    ids = [uuid.UUID(i["id"]) for i in series["items"]]
    at = datetime.now(UTC)
    with app.state.db.sessionmaker() as db:
        ok, bad = (db.get(ScheduleItem, i) for i in ids)
        ok.state, ok.posting_mode = "VERIFIED_SUCCESS", "live"
        bad.state, bad.reason = "UNKNOWN", "AGENT_LOST_AFTER_SUBMIT"
        for item in (ok, bad, bad):  # the repeat is ignored
            notify.on_post_event(db, item, app.state.settings)
        db.commit()
        ws = ok.workspace_id
        rows = db.scalars(select(Notification).where(Notification.workspace_id == ws)).all()
        assert sorted((r.kind, r.batch) for r in rows) == [("posting", True), ("problems", False)]

        bot.clear()
        mine = lambda: [p for _, p in bot if p.get("chat_id") == chat_id]  # noqa: E731 - other tests share the outbox
        notify.send_pending(db, "123:test", at)
        db.commit()
        assert len(mine()) == 1 and mine()[0]["text"].startswith("⚠️")
        assert mine()[0]["reply_markup"]["inline_keyboard"]  # phase 1.5: problems carry buttons
        # The success waits for the hour, then goes as one message.
        notify.send_pending(db, "123:test", at + timedelta(minutes=10))
        assert len(mine()) == 1
        notify.send_pending(db, "123:test", at + notify.BATCH_EVERY + timedelta(minutes=1))
        db.commit()
        assert len(mine()) == 2 and mine()[1]["text"].startswith("✅ โพสต์สำเร็จ 1 รายการ")
        assert "reply_markup" not in mine()[1]
        assert all(r.sent_at for r in db.scalars(select(Notification).where(Notification.workspace_id == ws)).all())


def test_a_blocked_chat_is_unlinked(shop, client, bot, app, monkeypatch):
    link(shop, client, 930_000_000 + uuid.uuid4().int % 1_000_000)
    chat = uuid.UUID(shop.acc.get("/v1/notifications").json()["chats"][0]["id"])
    shop.acc.post("/v1/notifications/test", json={"chat_ref": str(chat)})

    def blocked(*a, **k):
        raise telegram.TelegramError("403 Forbidden: bot was blocked by the user", 403)

    monkeypatch.setattr(telegram, "call", blocked)
    with app.state.db.sessionmaker() as db:
        notify.send_pending(db, "123:test", datetime.now(UTC))
        db.commit()
        assert db.get(TelegramChat, chat).unlinked_at is not None


def test_bot_removed_from_a_group_unlinks_it(shop, client, bot):
    chat_id = -(940_000_000 + uuid.uuid4().int % 1_000_000)
    link(shop, client, chat_id)
    hook(client, {"update_id": 2, "my_chat_member": {"chat": {"id": chat_id, "type": "group"},
                                                     "new_chat_member": {"status": "kicked"}}})
    assert shop.acc.get("/v1/notifications").json()["chats"] == []


def test_account_numbers_from_the_agent_and_the_daily_summary(shop, client, bot, app, onboard):
    link(shop, client, 950_000_000 + uuid.uuid4().int % 1_000_000)
    headers = {"Authorization": f"Bearer {shop.w.session}"}
    numbers = {"serial": shop.serial, "account": "handle0", "followers": 1984, "following": 405, "likes": 7412,
               "video_views": [328, 132, 108]}
    assert client.post("/v1/agent/account-stats", json=numbers, headers=headers).status_code == 201
    assert client.post("/v1/agent/account-stats", json=numbers | {"serial": "NOTMINE1"}, headers=headers).status_code == 404
    other = shop.__class__(onboard(), client, shop.clip_bytes)
    assert client.post("/v1/agent/account-stats", json=numbers,
                       headers={"Authorization": f"Bearer {other.w.session}"}).status_code == 404  # A's phone, B's Agent

    stat = shop.acc.get("/v1/notifications/stats").json()["items"][0]["stat"]
    assert stat["followers"] == 1984 and stat["video_views"] == [328, 132, 108]
    assert other.acc.get("/v1/notifications/stats").json()["items"][0]["stat"] is None

    with app.state.db.sessionmaker() as db:
        device = db.get(Device, uuid.UUID(shop.devices[0]))
        db.add(AccountStat(workspace_id=device.workspace_id, device_id=device.id, followers=1900, likes=7000,
                           video_views=[], captured_at=datetime.now(UTC) - timedelta(days=1)))
        db.commit()
        text = notify.summary_text(db, device, datetime.now(UTC))
        assert "ผู้ติดตาม 1,984 (+84)" in text and "ถูกใจ 7,412 (+412)" in text and "รวม 568" in text

        rule = db.scalars(select(NotifyRule).where(NotifyRule.workspace_id == device.workspace_id)).first()
        at = datetime.now(notify.TZ).replace(hour=rule.summary_hour, minute=5).astimezone(UTC)
        notify.summaries(db, at)
        notify.summaries(db, at)  # once a day per phone
        db.commit()
        rows = db.scalars(select(Notification).where(Notification.workspace_id == device.workspace_id,
                                                     Notification.kind == "summary")).all()
        assert len(rows) == 1 and rows[0].text.startswith("📊")


def test_the_webhook_goes_to_the_https_address_and_its_errors_are_shown(app, monkeypatch):
    settings = app.state.settings.model_copy(update={
        "telegram_bot_token": "123:test", "telegram_webhook_secret": SECRET,
        "public_api_base": "http://127.0.0.1:8000", "web_origin": "https://punpun.example"})
    hook_url = "https://punpun.example/v1/telegram/webhook"
    assert telegram.webhook_url(settings) == hook_url  # staging: API and web on one https origin
    assert telegram.webhook_url(settings.model_copy(update={"web_origin": "http://localhost:5173"})) is None
    assert telegram.webhook_url(settings.model_copy(update={"telegram_webhook_base": "https://api.example/"})) == \
        "https://api.example/v1/telegram/webhook"

    info = {"url": "", "pending_update_count": 2}
    made: list[tuple[str, dict]] = []

    def fake(token, method, payload, timeout=10.0):
        made.append((method, payload))
        if method == "setWebhook":
            info["url"] = payload["url"]
        return dict(info)

    monkeypatch.setattr(telegram, "call", fake)
    at = datetime.now(UTC)
    got = telegram.ensure_webhook(settings, at=at)
    assert got["ok"] and got["pending"] == 2
    assert [p for m, p in made if m == "setWebhook"] == [{"url": hook_url, "secret_token": SECRET,
                                                         "allowed_updates": ["message", "my_chat_member", "callback_query"]}]
    made.clear()
    assert telegram.ensure_webhook(settings, at=at)["ok"] and not [m for m, _ in made if m == "setWebhook"]
    telegram.ensure_webhook(settings, force=True, at=at)  # on start: registered again (the secret may have changed)
    assert [m for m, _ in made].count("setWebhook") == 1

    info |= {"last_error_date": int(at.timestamp()) - 60, "last_error_message": "Wrong response from the webhook: 404"}
    bad = telegram.ensure_webhook(settings, at=at)
    assert not bad["ok"] and "404" in bad["error"]
    assert telegram.ensure_webhook(settings, at=at + timedelta(minutes=20))["ok"]  # an old error is not shown
    assert "SECRET" in telegram.ensure_webhook(settings.model_copy(update={"telegram_webhook_secret": ""}))["error"]
