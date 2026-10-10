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
        return {"id": f"cs_test_{len(sessions)}_{uuid.uuid4().hex[:6]}", "url": "https://checkout.stripe.com/c/pay/x"}

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
