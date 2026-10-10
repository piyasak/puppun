"""Stripe through the API (PO 2026-10-10, D06): checkout makes a Checkout Session for the server's
amount; only a webhook with a valid Stripe-Signature changes the subscription, once. The call to
Stripe is replaced here (no network, no keys); webhooks are signed exactly as Stripe signs them."""

from __future__ import annotations

import json
import time
import uuid

import pytest
from api_test_tokens import SIGNING_KEY, SUPABASE_URL, mint, new_identity
from fastapi.testclient import TestClient

from clipflow_api import stripe_provider
from clipflow_api.app import create_app
from clipflow_api.config import Settings

WEBHOOK_SECRET = "whsec_test_" + "k" * 24


@pytest.fixture
def stripe_app(migrated_url, storage, monkeypatch):
    sessions = []

    def fake_checkout(key, **kw):
        assert key == "sk_test_fake"
        sessions.append(kw)
        # real Session ids are ~66 characters (the 500 on staging came from a 64-character column)
        return {"id": f"cs_test_{len(sessions)}_" + uuid.uuid4().hex * 2, "url": "https://checkout.stripe.com/c/pay/x"}

    monkeypatch.setattr(stripe_provider, "create_checkout", fake_checkout)
    settings = Settings(app_env="staging", database_url=migrated_url, supabase_url=SUPABASE_URL,
                        agent_auth_rate_per_minute=10_000, billing_provider="stripe",
                        stripe_secret_key="sk_test_fake", stripe_webhook_secret=WEBHOOK_SECRET,
                        web_origin="https://punpun.example")
    app = create_app(settings, resolve_key=lambda token: SIGNING_KEY.public_key(), storage=storage)
    return TestClient(app), sessions


def onboard(client):
    uid, email = new_identity()
    headers = {"Authorization": f"Bearer {mint(uid, email)}"}
    assert client.post("/v1/onboarding", json={"username": f"u{uuid.uuid4().hex[:10]}", "accept_rights": True},
                       headers=headers).status_code == 201
    return headers


def send(client, event: dict, secret=WEBHOOK_SECRET, at=None):
    body = json.dumps(event).encode()
    return client.post("/v1/billing/webhooks/stripe", content=body,
                       headers={"Stripe-Signature": stripe_provider.sign(secret, body, at)})


def completed(session_id, amount=40000, status="paid", kind="checkout.session.completed"):
    return {"id": f"evt_{uuid.uuid4().hex[:12]}", "type": kind, "created": int(time.time()),
            "data": {"object": {"object": "checkout.session", "id": session_id, "amount_total": amount,
                                "currency": "thb", "payment_status": status}}}


def test_card_payment_through_stripe_checkout(stripe_app):
    client, sessions = stripe_app
    h = onboard(client)
    assert "Stripe (โหมดทดสอบ)" in client.get("/v1/billing/plans").json()["note"]
    out = client.post("/v1/billing/checkout", json={"plan_code": "pro", "idempotency_key": uuid.uuid4().hex,
                                                     "amount_satang": 1}, headers=h)
    assert out.status_code == 201, out.text
    pay = out.json()
    assert pay["checkout_url"].startswith("https://checkout.stripe.com/") and pay["amount_satang"] == 40000
    sent = sessions[0]
    assert sent["amount_satang"] == 40000 and sent["currency"] == "THB"  # the server's amount, not the client's
    assert sent["success_url"] == f"https://punpun.example/billing?payment={pay['id']}"
    assert client.get("/v1/billing/subscription", headers=h).json()["status"] == "trial"  # the redirect grants nothing

    event = completed(_ref(client, pay["id"]))
    ok = send(client, event)
    assert ok.status_code == 200 and ok.json()["applied"] == "started"
    sub = client.get("/v1/billing/subscription", headers=h).json()
    assert (sub["status"], sub["plan"]["code"]) == ("active", "pro")
    assert send(client, event).json() == {"duplicate": True}  # Stripe retries: granted once


def _ref(client, payment_id) -> str:
    """The Session id the server stored as provider_ref (not exposed to customers)."""
    from clipflow_api.models import Payment

    app = client.app
    with app.state.db.sessionmaker() as s:
        return s.get(Payment, uuid.UUID(payment_id)).provider_ref


def test_promptpay_pays_later_and_failures_grant_nothing(stripe_app):
    client, _ = stripe_app
    h = onboard(client)
    pay = client.post("/v1/billing/checkout", json={"plan_code": "starter", "idempotency_key": uuid.uuid4().hex},
                      headers=h).json()
    ref = _ref(client, pay["id"])
    assert send(client, completed(ref, 20000, status="unpaid")).json()["outcome"] == "ignored_out_of_order"  # still pending
    assert client.get("/v1/billing/subscription", headers=h).json()["status"] == "trial"  # waiting for PromptPay
    assert send(client, completed(ref, 20000, kind="checkout.session.async_payment_succeeded")).json()["applied"] == "started"

    h2 = onboard(client)
    other = client.post("/v1/billing/checkout", json={"plan_code": "starter", "idempotency_key": uuid.uuid4().hex},
                        headers=h2).json()
    ref2 = _ref(client, other["id"])
    assert send(client, completed(ref2, 20000, status="unpaid", kind="checkout.session.expired")).json()["outcome"] == "applied"
    assert client.get(f"/v1/billing/payments/{other['id']}", headers=h2).json()["status"] == "failed"
    assert client.get("/v1/billing/subscription", headers=h2).json()["status"] == "trial"


def test_bad_signatures_wrong_amounts_and_other_events(stripe_app):
    client, _ = stripe_app
    h = onboard(client)
    pay = client.post("/v1/billing/checkout", json={"plan_code": "pro", "idempotency_key": uuid.uuid4().hex},
                      headers=h).json()
    ref = _ref(client, pay["id"])
    assert send(client, completed(ref), secret="whsec_attacker").status_code == 400
    assert send(client, completed(ref), at=int(time.time()) - 3600).status_code == 400  # replayed
    assert send(client, completed(ref, amount=100)).json()["outcome"] == "amount_mismatch"
    assert client.get("/v1/billing/subscription", headers=h).json()["status"] == "trial"
    ignored = send(client, {"id": "evt_x", "type": "customer.created", "data": {"object": {"object": "customer"}}})
    assert ignored.status_code == 200 and ignored.json() == {"ignored": True}


def test_live_keys_are_refused_off_production(migrated_url, storage):
    settings = Settings(app_env="staging", database_url=migrated_url, supabase_url=SUPABASE_URL,
                        billing_provider="stripe", stripe_secret_key="sk_live_real", stripe_webhook_secret=WEBHOOK_SECRET)
    client = TestClient(create_app(settings, resolve_key=lambda token: SIGNING_KEY.public_key(), storage=storage))
    h = onboard(client)
    out = client.post("/v1/billing/checkout", json={"plan_code": "pro", "idempotency_key": uuid.uuid4().hex}, headers=h)
    assert out.status_code == 503 and out.json()["code"] == "PAYMENTS_NOT_READY"


def test_refresh_settles_a_payment_whose_webhook_never_came(stripe_app, monkeypatch):
    """Staging 2026-10-10: paid on Stripe's page, but no webhook got through, so the payment stayed
    pending. Asking Stripe for the Session (our key) settles it, once; a late webhook changes nothing."""
    client, _ = stripe_app
    h = onboard(client)
    pay = client.post("/v1/billing/checkout", json={"plan_code": "pro", "idempotency_key": uuid.uuid4().hex},
                      headers=h).json()
    ref = _ref(client, pay["id"])
    stripe_has = {"id": ref, "object": "checkout.session", "status": "open", "payment_status": "unpaid",
                  "amount_total": 40000, "currency": "thb", "url": "https://checkout.stripe.com/c/pay/again"}
    asked = []

    def fake_retrieve(key, session_id):
        asked.append(session_id)
        return dict(stripe_has)

    monkeypatch.setattr(stripe_provider, "retrieve_checkout", fake_retrieve)
    still_open = client.post(f"/v1/billing/payments/{pay['id']}/refresh", headers=h).json()
    assert still_open["status"] == "pending" and still_open["checkout_url"] == stripe_has["url"]  # back to Stripe's page

    stripe_has.update(status="complete", payment_status="paid")
    paid = client.post(f"/v1/billing/payments/{pay['id']}/refresh", headers=h).json()
    assert paid["status"] == "succeeded" and paid["applied"] == "started" and paid["checkout_url"] is None
    assert client.get("/v1/billing/subscription", headers=h).json()["status"] == "active"
    assert asked == [ref, ref]

    again = client.post(f"/v1/billing/payments/{pay['id']}/refresh", headers=h).json()
    assert again["status"] == "succeeded" and len(asked) == 2  # settled: Stripe is not asked again
    late = send(client, completed(ref))
    assert late.json()["outcome"] == "ignored_out_of_order"  # the webhook arriving later grants nothing more
    sub = client.get("/v1/billing/subscription", headers=h).json()
    assert sub["paid_cycles_ahead"] == 0


def test_refresh_marks_an_expired_session_failed_and_checks_ownership(stripe_app, monkeypatch):
    client, _ = stripe_app
    h = onboard(client)
    pay = client.post("/v1/billing/checkout", json={"plan_code": "starter", "idempotency_key": uuid.uuid4().hex},
                      headers=h).json()
    ref = _ref(client, pay["id"])
    monkeypatch.setattr(stripe_provider, "retrieve_checkout", lambda key, sid: {
        "id": ref, "object": "checkout.session", "status": "expired", "payment_status": "unpaid",
        "amount_total": 20000, "currency": "thb", "url": None})
    assert client.post(f"/v1/billing/payments/{pay['id']}/refresh", headers=onboard(client)).status_code == 404
    out = client.post(f"/v1/billing/payments/{pay['id']}/refresh", headers=h).json()
    assert out["status"] == "failed" and out["checkout_url"] is None
    assert client.get("/v1/billing/subscription", headers=h).json()["status"] == "trial"


def intent(payment_id, amount, kind="payment_intent.succeeded"):
    """What staging got (2026-10-10): an endpoint subscribed to PaymentIntent events only."""
    return {"id": f"evt_{uuid.uuid4().hex[:12]}", "type": kind, "created": int(time.time()),
            "data": {"object": {"object": "payment_intent", "id": f"pi_{uuid.uuid4().hex[:12]}", "amount": amount,
                                "amount_received": amount if kind.endswith("succeeded") else 0, "currency": "thb",
                                "metadata": {"payment_id": payment_id}, "status": "succeeded",
                                "payment_method_types": ["promptpay"]}}}


def test_payment_intent_events_settle_by_our_payment_id(stripe_app):
    client, _ = stripe_app
    h = onboard(client)
    pay = client.post("/v1/billing/checkout", json={"plan_code": "business", "idempotency_key": uuid.uuid4().hex},
                      headers=h).json()
    ref = _ref(client, pay["id"])
    assert send(client, completed(ref, 88800, status="unpaid")).json()["outcome"] == "ignored_out_of_order"
    ok = send(client, intent(pay["id"], 88800))
    assert ok.status_code == 200 and ok.json()["applied"] == "started"
    assert client.get("/v1/billing/subscription", headers=h).json()["plan"]["code"] == "business"
    late = send(client, completed(ref, 88800, kind="checkout.session.async_payment_succeeded"))
    assert late.json()["outcome"] == "ignored_out_of_order"  # both subscriptions on: granted once
    assert client.get("/v1/billing/subscription", headers=h).json()["paid_cycles_ahead"] == 0

    h2 = onboard(client)
    other = client.post("/v1/billing/checkout", json={"plan_code": "pro", "idempotency_key": uuid.uuid4().hex},
                        headers=h2).json()
    assert send(client, intent(other["id"], 100)).json()["outcome"] == "amount_mismatch"
    failed = send(client, intent(other["id"], 40000, kind="payment_intent.payment_failed"))
    assert failed.json()["outcome"] == "applied"
    assert client.get(f"/v1/billing/payments/{other['id']}", headers=h2).json()["status"] == "failed"
    stray = send(client, intent("not-ours", 5000))  # a dashboard payment without our metadata
    assert stray.status_code == 200 and stray.json() == {"ignored": True}
