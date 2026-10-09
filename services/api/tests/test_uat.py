"""P7.1 critical UAT cases (PRD §O.13) that are not already covered by one named test elsewhere.

T01 sweeps every route that takes an id: another tenant gets exactly what a missing id gets, and
nothing of A's changes. T14, T19, T22 and T23 drive the posting and retention paths end to end.
The full T01–T25 map, with the test for each case, is `docs/uat/p7-uat.md`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from api_test_shop import Shop, Worker, claim, ev, expire, items, schedule, set_times
from api_test_tokens import SIGNING_KEY, SUPABASE_URL
from sqlalchemy import select, update
from test_billing import move_cycle

from clipflow_api import retention
from clipflow_api.app import create_app
from clipflow_api.config import Settings
from clipflow_api.models import Clip, ScheduleItem

# --- T01: A's ids through every route, called by B ------------------------------------------------

PARAM = {"environment_id": "env", "token_id": "token", "agent_id": "agent", "device_id": "device",
         "job_id": "job", "clip_id": "clip", "series_id": "series", "item_id": "item", "payment_id": "payment"}
# Bodies that pass validation, so the ownership check is what answers.
BODY = {
    ("patch", "/v1/environments/{environment_id}"): {"name": "taken"},
    ("patch", "/v1/devices/{device_id}"): {"display_name": "taken"},
    ("patch", "/v1/clips/{clip_id}/metadata"): {"expected_version": 1, "caption": "taken"},
    ("post", "/v1/clips/{clip_id}/approve"): {"metadata_version": 1},
    ("post", "/v1/clips/{clip_id}/unapprove"): {"metadata_version": 1},
    ("patch", "/v1/schedule-items/{item_id}"): {"expected_state_version": 1, "scheduled_local": "2030-01-01T10:00"},
    ("post", "/v1/schedule-items/{item_id}/resolve"): {"decision": "still_unknown", "evidence": "x" * 12,
                                                       "expected_state_version": 1},
    ("post", "/v1/schedule-items/{item_id}/retry"): {"expected_state_version": 1},
    ("post", "/v1/schedules/{series_id}/resume/preview"): {"expected_version": 1},
    ("post", "/v1/schedules/{series_id}/resume"): {"expected_version": 1},
}
AGENT_ROUTES = [("post", "/v1/agent/jobs/{job_id}/events", {"event_id": "e1" * 8, "type": "completed"}),
                ("post", "/v1/agent/posts/{item_id}/events", {"event_id": "e1" * 8, "type": "TRANSFERRING"}),
                ("put", "/v1/agent/jobs/{job_id}/clips/{index}/file", None)]


def _id_routes(app):
    for path, ops in app.openapi()["paths"].items():
        names = [p.strip("{}") for p in path.split("/") if p.startswith("{")]
        if path.startswith(("/v1/agent/", "/v1/admin/", "/v1/media/", "/v1/billing/webhooks")) or not names:
            continue
        assert all(n in PARAM for n in names), f"T01 does not know how to fill {path}"  # new route: add it here
        for method in ops:
            yield method, path, names


def _snapshot(a, ids):
    return [a.get(f"/v1/environments/{ids['env']}").json(), a.get(f"/v1/jobs/{ids['job']}").json(),
            a.get(f"/v1/clips/{ids['clip']}").json(), a.get(f"/v1/schedules/{ids['series']}").json(),
            a.get("/v1/devices").json(), a.get("/v1/agent-tokens").json(), a.get("/v1/agents").json(),
            a.get(f"/v1/billing/payments/{ids['payment']}").json()]


def test_t01_another_tenant_gets_what_a_missing_id_gets_on_every_route(shop, onboard, client, app, real_clip):
    a = shop
    series = schedule(a, clips=1)
    pay = a.acc.post("/v1/billing/checkout", json={"plan_code": "pro", "idempotency_key": uuid.uuid4().hex}).json()
    ids = {"env": a.env["id"], "token": a.token_id, "agent": a.acc.get("/v1/agents").json()["items"][0]["id"],
           "device": a.devices[0], "job": series["job_id"], "clip": series["items"][0]["clip_id"],
           "series": series["id"], "item": series["items"][0]["id"], "payment": pay["id"]}
    before = _snapshot(a.acc, ids)
    b = Shop(onboard(), client, real_clip)

    checked = 0
    for method, path, names in _id_routes(app):
        body = BODY.get((method, path), {})
        theirs = path.format(**{n: ids[PARAM[n]] for n in names})
        missing = path.format(**{n: str(uuid.uuid4()) for n in names})
        got = getattr(b.acc.client, method)(theirs, headers=b.acc.headers(), **({"json": body} if method != "get" else {}))
        ref = getattr(b.acc.client, method)(missing, headers=b.acc.headers(), **({"json": body} if method != "get" else {}))
        assert got.status_code in (404, 422) and got.status_code == ref.status_code, (method, path, got.text)
        assert got.json().get("code") == ref.json().get("code"), (method, path)
        checked += 1
    for method, path, body in AGENT_ROUTES:
        theirs = path.format(job_id=ids["job"], item_id=ids["item"], index=1)
        kw = {"json": body} if body else {"content": b"x"}
        got = getattr(b.w.client, method)(theirs, headers={"Authorization": f"Bearer {b.w.session}"}, **kw)
        assert got.status_code == 404, (method, path, got.text)
        checked += 1
    signed = a.acc.get(f"/v1/clips/{ids['clip']}/media").json()["url"]
    assert client.get(signed).status_code == 200
    tampered = signed[:-1] + ("0" if signed[-1] != "0" else "1")
    assert client.get(signed.split("?")[0]).status_code in (403, 422)  # the file itself needs A's signature
    assert client.get(tampered).status_code == 404  # a bad signature looks like a missing file
    assert checked >= 28  # 25 web routes with ids + 3 Agent routes on 2026-10-09; it only grows
    assert _snapshot(a.acc, ids) == before  # nothing of A's changed


# --- T14: cancel after a claim ---------------------------------------------------------------------

def test_t14_cancel_after_claim_leaves_the_started_post_to_finish(shop, app):
    series = schedule(shop, clips=3)
    set_times(app, series["id"], [-1, 60, 120])
    post = claim(shop.w, [shop.serial])
    ev(shop.w, post["id"], "TRANSFERRING")
    refused = shop.acc.post(f"/v1/schedule-items/{post['id']}/cancel")
    assert refused.status_code == 409 and refused.json()["code"] == "ITEM_NOT_CANCELLABLE"
    assert shop.acc.post(f"/v1/schedules/{series['id']}/cancel").status_code == 200
    states = [(i["state"], i["reason"]) for i in items(shop, series["id"])]
    assert states == [("TRANSFERRING", None), ("CANCELLED", "SERIES_CANCELLED"), ("CANCELLED", "SERIES_CANCELLED")]
    # The started post is not claimed to be stopped: it reports its own end.
    ev(shop.w, post["id"], "PREPARING")
    assert ev(shop.w, post["id"], "DRY_RUN_DONE").json()["state"] == "DRY_RUN_DONE"
    assert claim(shop.w, [shop.serial]) is None


# --- T19: server restart and redelivery ------------------------------------------------------------

@pytest.fixture
def restarted(migrated_url, storage):
    """A second server process on the same database: what the Agent sees after a restart."""
    from fastapi.testclient import TestClient
    settings = Settings(app_env="test", database_url=migrated_url, supabase_url=SUPABASE_URL,
                        agent_auth_rate_per_minute=10_000)
    return TestClient(create_app(settings, resolve_key=lambda token: SIGNING_KEY.public_key(), storage=storage,
                                 posting_mode="live"))


def test_t19_restart_never_hands_out_a_submitted_post_again(shop, app, live_client, restarted):
    series = schedule(shop, clips=2)
    set_times(app, series["id"], [-2, -1])
    lw = Worker(live_client, shop.acc.username, shop.token, shop.w.installation_id)
    assert lw.auth().status_code == 200
    first = claim(lw, [shop.serial])
    for kind in ("TRANSFERRING", "PREPARING", "SUBMITTING"):
        ev(lw, first["id"], kind)

    # The server restarts; the same Agent signs in again on the new process.
    rw = Worker(restarted, shop.acc.username, shop.token, shop.w.installation_id)
    assert rw.auth().status_code == 200
    assert ev(lw, first["id"], "VERIFYING").json()["code"] == "AGENT_SESSION_ENDED"  # the old session is fenced
    assert claim(rw, [shop.serial]) is None  # the phone is busy with a post between Submit and its result
    expire(app, first["id"])
    assert claim(rw, [shop.serial]) is None  # redelivery never repeats a submitted post
    assert items(shop, series["id"])[0]["state"] == "UNKNOWN"

    # Before Submit, the same item is redelivered (one lease at a time), not copied.
    unknown = items(shop, series["id"])[0]
    assert shop.acc.post(f"/v1/schedule-items/{first['id']}/resolve",
                         json={"decision": "found_published", "evidence": "พบโพสต์ t19 บนบัญชี handle0",
                               "expected_state_version": unknown["state_version"]}).status_code == 200
    second = claim(rw, [shop.serial])
    ev(rw, second["id"], "TRANSFERRING")
    expire(app, second["id"])
    again = claim(rw, [shop.serial])
    assert again["id"] == second["id"]
    with app.state.db.sessionmaker() as s:
        row = s.get(ScheduleItem, uuid.UUID(second["id"]))
        assert row.attempts == 2 and row.submitted_at is None


# --- T22: subscription ends while posts wait or are being submitted ----------------------------------

def test_t22_expiry_holds_waiting_posts_and_lets_a_submitted_one_finish(shop, app, live_client):
    series = schedule(shop, clips=2)
    set_times(app, series["id"], [-2, -1])
    lw = Worker(live_client, shop.acc.username, shop.token, shop.w.installation_id)
    assert lw.auth().status_code == 200
    ws = shop.acc.body["workspace"]["id"]

    first = claim(lw, [shop.serial])
    for kind in ("TRANSFERRING", "PREPARING", "SUBMITTING"):
        ev(lw, first["id"], kind)
    move_cycle(app, ws, end_in=-timedelta(minutes=1))
    done = ev(lw, first["id"], "VERIFIED_SUCCESS",
              evidence={"method": "caption_marker", "value": "t22", "account": "handle0"})
    assert done.json()["state"] == "VERIFIED_SUCCESS"  # a post already submitted is followed to its result

    move_cycle(app, ws, end_in=timedelta(days=1))
    second = claim(lw, [shop.serial])
    ev(lw, second["id"], "TRANSFERRING")
    ev(lw, second["id"], "PREPARING")
    move_cycle(app, ws, end_in=-timedelta(minutes=1))
    refused = ev(lw, second["id"], "SUBMITTING")
    assert refused.status_code == 409 and refused.json()["details"]["reason"] == "SUBSCRIPTION_INACTIVE"
    item = items(shop, series["id"])[1]
    assert (item["state"], item["reason"], item["submitted_at"]) == ("SCHEDULED", "SUBSCRIPTION_INACTIVE", None)
    assert claim(lw, [shop.serial]) is None  # waits, not parked, until renewed


# --- T23: storage cleanup while a job is running ---------------------------------------------------

def test_t23_cleanup_never_deletes_files_of_a_running_job(shop, app, storage):
    body = {"idempotency_key": uuid.uuid4().hex, "environment_id": shop.env["id"], "requested_clips": 2,
            "source": {"kind": "url", "url": "https://www.bilibili.tv/en/video/4800844531374592"},
            "clip_min_s": 15, "clip_max_s": 20, "review_mode": "review"}
    job_id = shop.acc.post("/v1/jobs", json=body).json()["id"]
    shop.w.prepare(job_id, possible=2)
    shop.w.report(job_id, 1, shop.clip_bytes)
    assert shop.w.upload(job_id, 1, shop.clip_bytes).status_code == 200  # clip 2 still rendering
    with app.state.db.sessionmaker() as s:
        clip = s.scalars(select(Clip).where(Clip.job_id == uuid.UUID(job_id))).one()
        s.execute(update(Clip).where(Clip.id == clip.id).values(uploaded_at=datetime.now(UTC) - timedelta(days=90)))
        s.commit()
        key = clip.storage_key
        out = retention.sweep(s, storage, datetime.now(UTC))
        s.commit()
    assert str(clip.id) in out.kept_in_use and str(clip.id) not in out.deleted
    assert storage.exists(key)

