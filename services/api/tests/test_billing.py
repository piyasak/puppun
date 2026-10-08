"""P6 (sandbox) — G6-02 success/fail/pending, G6-03 forged/repeated/out-of-order events,
G6-04 cycles: renewal, plan change at the next cycle, expiry, quota reset exactly once.

Time moves by editing the subscription's cycle in the throwaway database; everything else goes
through the API, including signed provider events.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from api_test_shop import FULL_DAY, claim, items, set_times
from sqlalchemy import select, update

from clipflow_api import billing
from clipflow_api.models import Subscription

SECRET_HEADER = "X-Sandbox-Signature"


def secret(app) -> bytes:
    from clipflow_api.routers.billing import sandbox_secret

    class R:  # the router reads the secret from app.state
        def __init__(self, app):
            self.app = app

    return sandbox_secret(R(app))


def buy(acc, code="pro", key=None):
    resp = acc.post("/v1/billing/checkout", json={"plan_code": code, "idempotency_key": key or uuid.uuid4().hex})
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def deliver(client, app, payment_ref, kind, amount, currency="THB", event_id=None, sign_with=None):
    body = json.dumps({"event_id": event_id or f"evt_{uuid.uuid4().hex}", "type": kind, "provider_ref": payment_ref,
                       "amount": amount, "currency": currency, "occurred_at": datetime.now(UTC).isoformat()}).encode()
    sig = billing.sign(sign_with or secret(app), body)
    return client.post("/v1/billing/webhooks/sandbox", content=body, headers={SECRET_HEADER: sig}), body, sig


def ref_of(app, payment_id):
    from clipflow_api.models import Payment

    with app.state.db.sessionmaker() as s:
        return s.get(Payment, uuid.UUID(payment_id)).provider_ref


def sub_state(acc):
    return acc.get("/v1/billing/subscription").json()


def move_cycle(app, workspace_id, *, end_in):
    """Shift the current cycle so it ends `end_in` from now (negative = already over)."""
    with app.state.db.sessionmaker() as s:
        sub = s.scalars(select(Subscription).where(Subscription.workspace_id == uuid.UUID(workspace_id))).one()
        length = sub.current_period_end - sub.current_period_start
        end = datetime.now(UTC) + end_in
        s.execute(update(Subscription).where(Subscription.id == sub.id)
                  .values(current_period_start=end - length, current_period_end=end))
        s.commit()


def ws_id(acc):
    return acc.body["workspace"]["id"]


def test_plans_are_examples_and_checkout_prices_come_from_the_server(onboard):
    acc = onboard()
    plans = acc.get("/v1/billing/plans").json()
    assert [p["code"] for p in plans["items"]] == ["starter", "pro", "business"]
    assert all(p["example_price"] for p in plans["items"]) and "ตัวอย่าง" in plans["note"]
    key = uuid.uuid4().hex
    first = acc.post("/v1/billing/checkout", json={"plan_code": "pro", "idempotency_key": key, "amount_satang": 1})
    assert first.status_code == 201 and first.json()["amount_satang"] == 99000  # client amount ignored
    again = acc.post("/v1/billing/checkout", json={"plan_code": "pro", "idempotency_key": key})
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert first.json()["status"] == "pending" and first.json()["checkout_url"].startswith("/billing/sandbox/")
    assert acc.post("/v1/billing/checkout", json={"plan_code": "trial", "idempotency_key": uuid.uuid4().hex}).status_code == 404


def test_success_fail_and_pending_through_the_sandbox(onboard):  # G6-02
    acc = onboard()
    assert sub_state(acc)["status"] == "trial"
    failed = buy(acc)
    out = acc.post(f"/v1/billing/sandbox/{failed['id']}/simulate", json={"outcome": "failed"}).json()
    assert out["payment"]["status"] == "failed" and sub_state(acc)["status"] == "trial"
    pending = buy(acc)
    out = acc.post(f"/v1/billing/sandbox/{pending['id']}/simulate", json={"outcome": "pending"}).json()
    assert out["outcome"] == "ignored_out_of_order" and sub_state(acc)["plan"]["code"] == "trial"  # pending changes nothing
    paid = buy(acc)
    out = acc.post(f"/v1/billing/sandbox/{paid['id']}/simulate", json={"outcome": "succeeded"}).json()
    assert out["payment"]["status"] == "succeeded" and out["payment"]["applied"] == "started"
    state = sub_state(acc)
    assert (state["status"], state["plan"]["code"], state["quota"]["limit"], state["quota"]["used"]) == ("active", "pro", 150, 0)
    history = acc.get("/v1/billing/payments").json()["items"]
    assert [p["status"] for p in history] == ["succeeded", "pending", "failed"]


def test_forged_repeated_and_late_events_never_grant_twice(onboard, client, app):  # G6-03
    acc = onboard()
    pay = buy(acc)
    ref = ref_of(app, pay["id"])
    forged, _, _ = deliver(client, app, ref, "payment.succeeded", 99000, sign_with=b"not-the-secret")
    assert forged.status_code == 400 and forged.json()["code"] == "INVALID_SIGNATURE"
    unsigned = client.post("/v1/billing/webhooks/sandbox", content=b'{"event_id":"x"}')
    assert unsigned.status_code == 400
    cheap, _, _ = deliver(client, app, ref, "payment.succeeded", 100)  # signed, but not our amount
    assert cheap.json()["outcome"] == "amount_mismatch"
    assert sub_state(acc)["status"] == "trial"

    ok, body, sig = deliver(client, app, ref, "payment.succeeded", 99000)
    assert ok.json()["applied"] == "started"
    end = sub_state(acc)["cycle_end"]
    replay = client.post("/v1/billing/webhooks/sandbox", content=body, headers={SECRET_HEADER: sig})
    assert replay.json() == {"duplicate": True}
    late, _, _ = deliver(client, app, ref, "payment.failed", 99000)  # arrives after success
    assert late.json()["outcome"] == "ignored_out_of_order"
    again, _, _ = deliver(client, app, ref, "payment.succeeded", 99000)  # a second success event id
    assert again.json()["outcome"] == "ignored_out_of_order"
    state = sub_state(acc)
    assert state["cycle_end"] == end and state["paid_cycles_ahead"] == 0  # granted exactly once
    other = onboard()
    assert other.get(f"/v1/billing/payments/{pay['id']}").status_code == 404
    assert other.post(f"/v1/billing/sandbox/{pay['id']}/simulate", json={"outcome": "refunded"}).status_code == 404


def test_renewal_and_plan_change_take_over_at_the_cycle_boundary(onboard, app):  # G6-04
    acc = onboard()
    first = buy(acc, "pro")
    acc.post(f"/v1/billing/sandbox/{first['id']}/simulate", json={"outcome": "succeeded"})
    start = sub_state(acc)
    nxt = buy(acc, "business")
    out = acc.post(f"/v1/billing/sandbox/{nxt['id']}/simulate", json={"outcome": "succeeded"}).json()
    assert out["payment"]["applied"] == "queued"
    mid = sub_state(acc)
    assert mid["plan"]["code"] == "pro" and mid["next_plan"]["code"] == "business" and mid["paid_cycles_ahead"] == 1
    assert mid["cycle_start"] == start["cycle_start"]  # nothing changes until the boundary
    assert acc.post("/v1/billing/checkout", json={"plan_code": "starter",
                                                  "idempotency_key": uuid.uuid4().hex}).json()["code"] == "CHANGE_PENDING"

    move_cycle(app, ws_id(acc), end_in=-timedelta(minutes=1))  # the pro cycle is over
    after = sub_state(acc)
    assert (after["status"], after["plan"]["code"], after["paid_cycles_ahead"]) == ("active", "business", 0)
    assert after["cycle_start"] != start["cycle_start"] and after["quota"]["limit"] == 500
    assert after["quota"]["period"] == billing.cycle_key(datetime.fromisoformat(after["cycle_start"]))


def test_quota_resets_once_per_cycle_and_old_usage_stays_in_its_cycle(shop, app):  # G6-04
    first_job, _ = shop.job(clips=2)  # uses 2 units in the trial cycle
    before = sub_state(shop.acc)["quota"]
    assert before["used"] == 2
    pay = buy(shop.acc, "pro")
    shop.acc.post(f"/v1/billing/sandbox/{pay['id']}/simulate", json={"outcome": "succeeded"})
    fresh = sub_state(shop.acc)["quota"]
    assert fresh["used"] == 0 and fresh["period"] != before["period"]  # paid cycle starts with a full quota
    again = sub_state(shop.acc)["quota"]
    assert again == fresh  # reading twice does not reset anything
    renew = buy(shop.acc, "pro")
    shop.acc.post(f"/v1/billing/sandbox/{renew['id']}/simulate", json={"outcome": "succeeded"})
    shop.job(clips=1)
    move_cycle(app, ws_id(shop.acc), end_in=-timedelta(seconds=1))
    rolled = sub_state(shop.acc)["quota"]
    assert rolled["used"] == 0 and rolled["period"] != fresh["period"]
    job = shop.acc.get(f"/v1/jobs/{first_job}").json()
    assert job["quota"]["settled"] == 2  # earlier usage stays charged where it happened


def test_expired_subscription_blocks_new_jobs_and_holds_posts(shop, app):  # G6-04
    job_id, _ = shop.job(clips=1)
    series = shop.create(job_id, **FULL_DAY).json()
    set_times(app, series["id"], [-1])
    move_cycle(app, ws_id(shop.acc), end_in=-timedelta(minutes=1))  # trial over, nothing paid
    assert sub_state(shop.acc)["status"] == "expired"
    resp = shop.acc.post("/v1/jobs", json={"idempotency_key": uuid.uuid4().hex, "environment_id": shop.env["id"],
                                           "source": {"kind": "url", "url": "https://www.youtube.com/watch?v=x1"}})
    assert resp.status_code == 402 and resp.json()["code"] == "SUBSCRIPTION_EXPIRED"
    assert claim(shop.w, [shop.serial]) is None  # due post waits, not parked
    assert items(shop, series["id"])[0]["state"] == "SCHEDULED"
    pay = buy(shop.acc, "starter")
    shop.acc.post(f"/v1/billing/sandbox/{pay['id']}/simulate", json={"outcome": "succeeded"})
    assert sub_state(shop.acc)["status"] == "active"
    assert claim(shop.w, [shop.serial])["id"] == series["items"][0]["id"]  # renewed: it runs


def test_refund_of_a_queued_renewal_withdraws_it(onboard):
    acc = onboard()
    first = buy(acc, "pro")
    acc.post(f"/v1/billing/sandbox/{first['id']}/simulate", json={"outcome": "succeeded"})
    renew = buy(acc, "pro")
    acc.post(f"/v1/billing/sandbox/{renew['id']}/simulate", json={"outcome": "succeeded"})
    assert sub_state(acc)["paid_cycles_ahead"] == 1
    out = acc.post(f"/v1/billing/sandbox/{renew['id']}/simulate", json={"outcome": "refunded"}).json()
    assert out["payment"]["applied"] == "removed" and sub_state(acc)["paid_cycles_ahead"] == 0
    running = acc.post(f"/v1/billing/sandbox/{first['id']}/simulate", json={"outcome": "refunded"}).json()
    assert running["payment"]["applied"] == "needs_review"  # a running cycle is an admin decision
    assert sub_state(acc)["status"] == "active"


def test_sandbox_is_refused_on_a_production_server(migrated_url, storage):
    from api_test_tokens import SIGNING_KEY, SUPABASE_URL
    from fastapi.testclient import TestClient

    from clipflow_api.app import create_app
    from clipflow_api.config import Settings

    prod = TestClient(create_app(Settings(app_env="production", database_url=migrated_url, supabase_url=SUPABASE_URL),
                                 resolve_key=lambda t: SIGNING_KEY.public_key(), storage=storage))
    assert prod.post("/v1/billing/webhooks/sandbox", content=b"{}", headers={SECRET_HEADER: "x"}).status_code == 404
