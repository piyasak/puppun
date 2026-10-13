"""Authorized real posting (Q-42) on the normal (dry-run) server: a post goes out live only under an
admin's grant for the phone's account and only to an Agent that says it can post live; the grant use
is counted at SUBMITTING under a lock; revoked/used-up/expired grants are never pressed. No real post
happens here: the phone and TikTok are simulated."""

from __future__ import annotations

import uuid

import pytest
from api_test_shop import FULL_DAY, items, schedule, set_times
from sqlalchemy import select
from test_agent_live_post_http import Gallery, PostingUi

from agent.adb import Adb
from agent.post_runner import PostRunner
from agent.server_client import ServerClient
from clipflow_api import manage
from clipflow_api.models import AuditEvent, PostingGrant, ScheduleItem

REASON = "Pilot ลูกค้า A ได้รับอนุญาตโพสต์จริง 5 ครั้ง"


@pytest.fixture
def admin(onboard, app):
    acc = onboard()
    with app.state.db.sessionmaker() as s:
        assert manage.grant_role(s, acc.email, "admin") == 0
    return acc


def grant(admin, shop, account="handle0", max_posts=5, days=7, **extra):
    resp = admin.post(f"/v1/admin/workspaces/{shop.acc.body['workspace']['id']}/posting-grants",
                      json={"account": account, "max_posts": max_posts, "days": days, "reason": REASON} | extra)
    assert resp.status_code == 201, resp.text
    return resp.json()


def due(app, shop, clips=1):
    series = schedule(shop, clips=clips, **FULL_DAY)
    set_times(app, series["id"], [-1] * clips)
    return series


def claim(shop, live=True, serials=None):
    body = {"ready_serials": serials or [shop.serial]} | ({"can_post_live": True} if live else {})
    resp = shop.w.post("/v1/agent/posts/claim", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["post"]


def ev(shop, post, kind, **payload):
    return shop.w.post(f"/v1/agent/posts/{post['id']}/events", json={"event_id": uuid.uuid4().hex, "type": kind, **payload})


def to_preparing(shop, post):
    for kind in ("TRANSFERRING", "PREPARING"):
        assert ev(shop, post, kind).status_code == 200


def used(app, grant_id):
    with app.state.db.sessionmaker() as s:
        return s.get(PostingGrant, uuid.UUID(grant_id)).used_posts


def test_without_a_grant_every_post_is_a_dry_run(shop, app):
    due(app, shop)
    post = claim(shop)
    assert post["posting_mode"] == "dry_run" and post["grant"] is None
    to_preparing(shop, post)
    refused = ev(shop, post, "SUBMITTING")
    assert refused.status_code == 409 and refused.json()["code"] == "POSTING_DISABLED"
    assert ev(shop, post, "DRY_RUN_DONE").status_code == 200


def test_a_grant_makes_the_post_live_and_counts_one_use_at_submit(shop, app, admin):
    g = grant(admin, shop, account="@Handle0")  # stored like the phone's account: lower case, no "@"
    assert g["account"] == "handle0" and g["status"] == "active" and g["remaining"] == 5
    series = due(app, shop)
    post = claim(shop)
    assert post["posting_mode"] == "live" and post["grant"] == {"id": g["id"], "visibility": "only_me"}
    to_preparing(shop, post)
    assert ev(shop, post, "DRY_RUN_DONE").json()["code"] == "BAD_EVENT_ORDER"  # a live post is not a dry run
    assert used(app, g["id"]) == 0  # nothing counted before Submit
    assert ev(shop, post, "SUBMITTING").status_code == 200
    assert used(app, g["id"]) == 1
    assert ev(shop, post, "VERIFYING").status_code == 200
    done = ev(shop, post, "VERIFIED_SUCCESS", evidence={"method": "caption_marker", "value": "cfabc123",
                                                        "account": "handle0"})
    assert done.status_code == 200
    assert items(shop, series["id"])[0]["state"] == "VERIFIED_SUCCESS"
    assert used(app, g["id"]) == 1


def test_a_grant_for_another_account_does_not_apply(shop, app, admin):
    grant(admin, shop, account="someone_else")
    due(app, shop)
    post = claim(shop)
    assert post["posting_mode"] == "dry_run" and post["grant"] is None


def test_an_agent_that_cannot_post_live_never_gets_a_live_post(shop, app, admin):
    grant(admin, shop)
    due(app, shop)
    post = claim(shop, live=False)  # Agent 0.3.x: no can_post_live
    assert post["posting_mode"] == "dry_run" and post["grant"] is None


def test_room_is_shared_by_posts_already_handed_out(shop, app, admin):
    shop.acc.patch(f"/v1/environments/{shop.env['id']}", json={"name": shop.env["name"], "device_limit": 2})
    second = shop.phone("handle0")  # a second phone on the same TikTok account
    serial2 = next(d["serial"] for d in shop.acc.get("/v1/devices").json()["items"] if d["id"] == second)
    g = grant(admin, shop, max_posts=1)
    for device in (shop.devices[0], second):
        job_id, _ = shop.job(clips=1)
        series = shop.create(job_id, device=device, **FULL_DAY).json()
        set_times(app, series["id"], [-1])
    first = claim(shop, serials=[shop.serial])
    other = claim(shop, serials=[serial2])
    assert first["posting_mode"] == "live" and other["posting_mode"] == "dry_run"  # one post allowed, one in flight
    to_preparing(shop, first)
    assert ev(shop, first, "SUBMITTING").status_code == 200
    assert used(app, g["id"]) == 1


def test_a_grant_revoked_after_the_claim_is_never_pressed(shop, app, admin):
    g = grant(admin, shop)
    series = due(app, shop)
    post = claim(shop)
    to_preparing(shop, post)
    assert admin.post(f"/v1/admin/posting-grants/{g['id']}/revoke", json={"reason": "ลูกค้าขอหยุดโพสต์จริง"}).json()["status"] == "revoked"
    refused = ev(shop, post, "SUBMITTING")
    assert refused.status_code == 409 and refused.json()["code"] == "POSTING_NOT_ALLOWED"
    item = items(shop, series["id"])[0]
    assert (item["state"], item["reason"]) == ("NEEDS_ACTION", "POSTING_GRANT_REVOKED")
    assert used(app, g["id"]) == 0


def test_a_used_up_grant_refuses_at_submit(shop, app, admin):
    g = grant(admin, shop, max_posts=1)
    due(app, shop)
    post = claim(shop)
    to_preparing(shop, post)
    with app.state.db.sessionmaker() as s:  # used elsewhere in the meantime (e.g. a resolved retry)
        s.get(PostingGrant, uuid.UUID(g["id"])).used_posts = 1
        s.commit()
    assert ev(shop, post, "SUBMITTING").json()["details"]["reason"] == "POSTING_GRANT_USED_UP"
    assert used(app, g["id"]) == 1


def test_only_admins_give_grants_with_a_reason_and_customers_only_see_them(shop, onboard, app, admin):
    ws = shop.acc.body["workspace"]["id"]
    body = {"account": "handle0", "max_posts": 5, "days": 7, "reason": REASON}
    assert shop.acc.post(f"/v1/admin/workspaces/{ws}/posting-grants", json=body).status_code == 404
    support = onboard()
    with app.state.db.sessionmaker() as s:
        assert manage.grant_role(s, support.email, "support") == 0
    assert support.post(f"/v1/admin/workspaces/{ws}/posting-grants", json=body).json()["code"] == "ADMIN_ONLY"
    assert admin.post(f"/v1/admin/workspaces/{ws}/posting-grants", json=body | {"reason": "short"}).status_code == 422
    assert admin.post(f"/v1/admin/workspaces/{ws}/posting-grants", json=body | {"visibility": "public"}).status_code == 422
    g = grant(admin, shop)
    assert [x["id"] for x in support.get(f"/v1/admin/workspaces/{ws}/posting-grants").json()["items"]] == [g["id"]]
    mine = shop.acc.get("/v1/devices/posting-grants").json()["items"]
    assert [x["id"] for x in mine] == [g["id"]] and "reason" not in mine[0]
    assert onboard().get("/v1/devices/posting-grants").json()["items"] == []  # other tenants see nothing
    with app.state.db.sessionmaker() as s:
        row = s.scalars(select(AuditEvent).where(AuditEvent.action == "admin.posting_grant.create",
                                                 AuditEvent.target_id == uuid.UUID(g["id"]))).one()
    assert row.reason == REASON and str(row.actor_user_id) == str(admin.user_id)


def test_the_agent_posts_under_a_server_grant(shop, app, admin, server_url, tmp_path):
    """The real post runner on the normal server: no local ledger, the grant comes from the server."""
    shop.acc.patch(f"/v1/environments/{shop.env['id']}", json={"name": shop.env["name"], "registered_agent_limit": 2,
                                                              "concurrent_session_limit": 2, "device_limit": 1})
    g = grant(admin, shop, max_posts=1)
    series = due(app, shop)
    client = ServerClient(server_url)
    session = client.authenticate(shop.acc.username, shop.token, str(uuid.uuid4()))
    ui = PostingUi()
    runner = PostRunner(tmp_path / "agent-data", lambda: Adb(Gallery(shop.serial).run), log=lambda *_: None,
                        retry_wait_s=0.1, ui_factory=lambda adb, serial: ui)
    assert runner.run_once(client, lambda: session) == "VERIFIED_SUCCESS"
    assert ui.calls == ["account", "open", "only_me", "caption", "POST", "close"]
    assert items(shop, series["id"])[0]["evidence"]["method"] == "caption_marker"
    assert used(app, g["id"]) == 1

    second = due(app, shop)  # the one post is used: the next one is a dry run, nothing pressed
    ui2 = PostingUi()
    runner.ui_factory = lambda adb, serial: ui2
    assert runner.run_once(client, lambda: session) == "DRY_RUN_DONE"
    assert "POST" not in ui2.calls and items(shop, second["id"])[0]["state"] == "DRY_RUN_DONE"


def test_post_now_says_what_to_expect(shop, app, admin):
    job_id, clip_ids = shop.job(clips=2)
    key = lambda: uuid.uuid4().hex  # noqa: E731
    first = shop.acc.post(f"/v1/clips/{clip_ids[0]}/post-now", json={"device_id": shop.devices[0], "idempotency_key": key()})
    assert first.json()["posting_mode"] == "dry_run"
    grant(admin, shop)
    second = shop.acc.post(f"/v1/clips/{clip_ids[1]}/post-now", json={"device_id": shop.devices[0], "idempotency_key": key()})
    assert second.json()["posting_mode"] == "live"


# --- Q-48: an admin turns the account check off for a Workspace ------------------------------------------

def account_check(admin, shop, enabled, reason="PO ขอปิดการตรวจบัญชีให้ลูกค้าใช้ง่าย"):
    return admin.post(f"/v1/admin/workspaces/{shop.acc.body['workspace']['id']}/account-check",
                      json={"enabled": enabled, "reason": reason})


def test_only_an_admin_turns_the_account_check_off_and_it_is_audited(shop, app, admin, onboard):
    support = onboard()
    with app.state.db.sessionmaker() as s:
        assert manage.grant_role(s, support.email, "support") == 0
    ws = shop.acc.body["workspace"]["id"]
    assert admin.get(f"/v1/admin/workspaces/{ws}").json()["account_check"] is True  # on by default
    assert support.post(f"/v1/admin/workspaces/{ws}/account-check",
                        json={"enabled": False, "reason": "support ลองปิดการตรวจ"}).status_code == 403
    assert shop.acc.post(f"/v1/admin/workspaces/{ws}/account-check",
                         json={"enabled": False, "reason": "ลูกค้าลองปิดเอง"}).status_code == 404
    assert account_check(admin, shop, False, reason="short").status_code == 422  # a reason is required
    off = account_check(admin, shop, False)
    assert off.status_code == 200 and off.json()["account_check"] is False
    with app.state.db.sessionmaker() as s:
        row = s.scalars(select(AuditEvent).where(AuditEvent.action == "admin.account_check.set")).one()
        assert row.details == {"before": True, "after": False} and row.reason


def requeue(app):
    """The claimed post back to SCHEDULED, so the next claim sees it again (simulates a lost lease)."""
    with app.state.db.sessionmaker() as s:
        for it in s.scalars(select(ScheduleItem)).all():
            it.state, it.lease_session_id, it.lease_expires_at = "SCHEDULED", None, None
        s.commit()


def test_with_the_check_off_any_grant_covers_whatever_account_the_phone_has(shop, app, admin):
    g = grant(admin, shop, account="")  # any account
    assert g["account"] == "*"
    due(app, shop)
    assert claim(shop)["posting_mode"] == "dry_run"  # the check is still on: "*" never matches an account
    requeue(app)
    assert account_check(admin, shop, False).status_code == 200
    old = shop.w.post("/v1/agent/posts/claim", json={"ready_serials": [shop.serial], "can_post_live": True}).json()["post"]
    assert old["posting_mode"] == "dry_run"  # an Agent older than 0.5.7 keeps the old rules
    requeue(app)
    post = shop.w.post("/v1/agent/posts/claim", json={"ready_serials": [shop.serial], "can_post_live": True,
                                                       "can_skip_account_check": True}).json()["post"]
    assert post["posting_mode"] == "live" and post["grant"]["id"] == g["id"]
    assert post["device"]["account_check"] is False
    to_preparing(shop, post)
    assert ev(shop, post, "SUBMITTING").status_code == 200  # the phone's account is not compared
    assert used(app, g["id"]) == 1
    assert ev(shop, post, "VERIFYING").status_code == 200
    assert ev(shop, post, "VERIFIED_SUCCESS", evidence={"method": "caption_marker", "value": "cfabc123"}).status_code == 200


def test_with_the_check_off_a_phone_without_an_account_can_be_scheduled(shop, app, admin):
    shop.acc.patch(f"/v1/environments/{shop.env['id']}", json={"name": shop.env["name"], "device_limit": 2})
    phone = shop.phone(None)
    job_id, _ = shop.job(clips=1)
    assert shop.create(job_id, device=phone, **FULL_DAY).json()["code"] == "DEVICE_NEEDS_DETAILS"
    listed = next(d for d in shop.acc.get("/v1/devices").json()["items"] if d["id"] == phone)
    assert "expected_account" in listed["missing_details"]
    assert account_check(admin, shop, False).status_code == 200
    assert shop.create(job_id, device=phone, **FULL_DAY).status_code == 201
    listed = next(d for d in shop.acc.get("/v1/devices").json()["items"] if d["id"] == phone)
    assert "expected_account" not in listed["missing_details"]
