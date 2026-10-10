"""Stripe adapter (PO 2026-10-10, D06): signatures, event mapping, the Checkout request. No network:
these check our side of the contract; a real test-mode run needs the PO's Stripe test keys."""

from __future__ import annotations

import io
import json
import urllib.parse

import pytest

from clipflow_api import stripe_provider as sp

SECRET = "whsec_test_" + "x" * 24


def test_signature_matches_stripes_scheme_and_rejects_tampering_and_replays():
    body = b'{"id":"evt_1"}'
    header = sp.sign(SECRET, body, at=1_700_000_000)
    assert sp.verify(SECRET, body, header, now=1_700_000_100)
    assert not sp.verify(SECRET, body + b" ", header, now=1_700_000_100)  # body changed
    assert not sp.verify("whsec_other", body, header, now=1_700_000_100)  # other endpoint's secret
    assert not sp.verify(SECRET, body, header, now=1_700_000_000 + 301)  # older than 5 minutes
    assert not sp.verify(SECRET, body, None) and not sp.verify(SECRET, body, "v1=abc")
    rotated = header + ",v1=" + "0" * 64  # Stripe may send several v1 values while a secret rotates
    assert sp.verify(SECRET, body, rotated, now=1_700_000_100)


def session(status="paid", **extra):
    return {"object": "checkout.session", "id": "cs_test_1", "amount_total": 40000, "currency": "thb",
            "payment_status": status} | extra


@pytest.mark.parametrize(("kind", "status", "expected"), [
    ("checkout.session.completed", "paid", "payment.succeeded"),  # card
    ("checkout.session.completed", "unpaid", "payment.pending"),  # PromptPay: paid later
    ("checkout.session.async_payment_succeeded", "paid", "payment.succeeded"),
    ("checkout.session.async_payment_failed", "unpaid", "payment.failed"),
    ("checkout.session.expired", "unpaid", "payment.failed"),
])
def test_events_map_onto_payment_statuses(kind, status, expected):
    out = sp.normalize({"id": "evt_9", "type": kind, "created": 1_700_000_000, "data": {"object": session(status)}})
    assert out == {"event_id": "evt_9", "type": expected, "provider_ref": "cs_test_1", "amount": 40000,
                   "currency": "THB", "occurred_at": "2023-11-14T22:13:20+00:00"}


def test_other_events_are_not_acted_on():
    assert sp.normalize({"id": "evt_1", "type": "customer.created", "data": {"object": {"object": "customer"}}}) is None


def test_live_keys_only_on_production():
    assert sp.key_allowed("sk_test_abc", "staging") and sp.key_allowed("sk_test_abc", "production")
    assert not sp.key_allowed("sk_live_abc", "staging") and sp.key_allowed("sk_live_abc", "production")
    assert not sp.key_allowed("pk_test_abc", "staging")  # a publishable key cannot create sessions


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_checkout_request_carries_the_servers_amount_and_an_idempotency_key():
    sent = {}

    def opener(req, timeout):
        sent["req"], sent["timeout"] = req, timeout
        return Resp(json.dumps({"id": "cs_test_9", "url": "https://checkout.stripe.com/c/pay/cs_test_9"}).encode())

    out = sp.create_checkout("sk_test_abc", payment_id="pay-1", amount_satang=88800, currency="THB",
                             product="punpun Business (30 วัน)", success_url="https://app/billing?payment=pay-1",
                             cancel_url="https://app/billing", email="a@example.com", opener=opener)
    assert out == {"id": "cs_test_9", "url": "https://checkout.stripe.com/c/pay/cs_test_9"}
    req = sent["req"]
    form = dict(urllib.parse.parse_qsl(req.data.decode()))
    assert form["line_items[0][price_data][unit_amount]"] == "88800"
    assert form["line_items[0][price_data][currency]"] == "thb" and form["mode"] == "payment"
    assert form["client_reference_id"] == "pay-1" and form["metadata[payment_id]"] == "pay-1"
    assert req.get_header("Idempotency-key") == "checkout-pay-1"
    assert req.get_header("Authorization").startswith("Basic ")
    assert "sk_test_abc" not in req.full_url  # the key travels in the header only


def test_retrieve_asks_for_one_session_with_the_key_in_the_header():
    sent = {}

    def opener(req, timeout):
        sent["req"] = req
        return Resp(json.dumps({"id": "cs_test_abc", "status": "complete", "payment_status": "paid"}).encode())

    out = sp.retrieve_checkout("sk_test_abc", "cs_test_abc", opener=opener)
    assert out["payment_status"] == "paid"
    assert sent["req"].get_method() == "GET" and sent["req"].full_url == "https://api.stripe.com/v1/checkout/sessions/cs_test_abc"
    with pytest.raises(sp.StripeError):
        sp.retrieve_checkout("sk_test_abc", "../customers", opener=opener)  # only Session ids reach the URL
    assert sp.session_status("", {"status": "complete", "payment_status": "paid"}) == "payment.succeeded"
    assert sp.session_status("", {"status": "expired", "payment_status": "unpaid"}) == "payment.failed"
    assert sp.session_status("", {"status": "open", "payment_status": "unpaid"}) is None
