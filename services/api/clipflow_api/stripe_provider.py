"""Stripe as the payment provider (PO 2026-10-10, D06): Checkout Sessions + signed webhooks.

- Checkout: a one-off payment for one cycle (no auto-renew, D06), in THB, for the amount the server
  computed from the plan (never from the client). Stripe's hosted page offers the methods switched on
  in the Stripe dashboard (cards; PromptPay for Thailand). The Session id is the payment's provider_ref
  and our payment id travels as client_reference_id + metadata.
- Webhooks: the Stripe-Signature header (t=..., v1=HMAC-SHA256 of "t.payload" with the endpoint
  secret) is checked over the raw body with a 5-minute tolerance before anything is parsed. Events
  map onto the provider-neutral statuses in billing.apply_event (unique per (provider, event_id),
  statuses only move forward, amount and currency must match the payment).
- Keys come from the environment (Render dashboard), never from code or chat. A live key is refused
  unless APP_ENV=production, so staging can only ever use Stripe test mode.

No Stripe SDK: two HTTPS calls' worth of API, done with the standard library.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://api.stripe.com/v1"
TOLERANCE_S = 300
SESSION_ID = re.compile(r"cs_(test|live)_[A-Za-z0-9]{1,200}")

# Stripe event type -> our payment status (billing.EVENT_STATUS keys)
EVENTS = {
    "checkout.session.async_payment_succeeded": "payment.succeeded",
    "checkout.session.async_payment_failed": "payment.failed",
    "checkout.session.expired": "payment.failed",
}


class StripeError(Exception):
    pass


def key_allowed(secret_key: str, app_env: str) -> bool:
    """Test keys anywhere; live keys only on production (real money needs the G6 sign-off first)."""
    if secret_key.startswith(("sk_test_", "rk_test_")):
        return True
    return secret_key.startswith(("sk_live_", "rk_live_")) and app_env == "production"


def test_mode(secret_key: str) -> bool:
    return secret_key.startswith(("sk_test_", "rk_test_"))


def _form(params: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's nested form encoding: a[b][0][c]=v."""
    out = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            out += _form(value, name)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                out += _form(item, f"{name}[{i}]") if isinstance(item, dict) else [(f"{name}[{i}]", str(item))]
        elif value is not None:
            out.append((name, str(value)))
    return out


def create_checkout(secret_key: str, *, payment_id: str, amount_satang: int, currency: str, product: str,
                    success_url: str, cancel_url: str, email: str | None = None, opener=urllib.request.urlopen) -> dict:
    """A Checkout Session for one payment. Returns {"id", "url"}. The payment id is the idempotency key,
    so a retried request never makes a second Session."""
    params = {
        "mode": "payment",
        "client_reference_id": payment_id,
        "metadata": {"payment_id": payment_id},
        "payment_intent_data": {"metadata": {"payment_id": payment_id}},
        "line_items": [{"quantity": 1, "price_data": {
            "currency": currency.lower(), "unit_amount": amount_satang, "product_data": {"name": product}}}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "customer_email": email,
        "locale": "th",
    }
    session = _call(secret_key, "POST", "/checkout/sessions", data=urllib.parse.urlencode(_form(params)).encode(),
                    idempotency_key=f"checkout-{payment_id}", opener=opener)
    return {"id": session["id"], "url": session["url"]}


def retrieve_checkout(secret_key: str, session_id: str, opener=urllib.request.urlopen) -> dict:
    """The Session as Stripe has it now. Asked with our secret key over HTTPS, so it is as trustworthy
    as a signed webhook; it settles payments whose webhook never arrived (misconfigured endpoint)."""
    if not SESSION_ID.fullmatch(session_id):
        raise StripeError("not a Checkout Session id")
    return _call(secret_key, "GET", f"/checkout/sessions/{session_id}", opener=opener)


def _call(secret_key: str, method: str, path: str, *, data: bytes | None = None, idempotency_key: str | None = None,
          opener=urllib.request.urlopen) -> dict:
    auth = base64.b64encode(f"{secret_key}:".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with opener(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read()).get("error", {}).get("message", "")
        except ValueError:
            message = ""
        raise StripeError(f"Stripe {exc.code}: {message[:200]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StripeError(f"Stripe unreachable: {exc}") from None


def sign(secret: str, payload: bytes, at: int | None = None) -> str:
    """A Stripe-Signature header for `payload` (what Stripe sends; used by the tests)."""
    t = int(at if at is not None else time.time())
    mac = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(secret: str, payload: bytes, header: str | None, now: float | None = None) -> bool:
    if not secret or not header:
        return False
    parts = [p.split("=", 1) for p in header.split(",") if "=" in p]
    stamps = [v for k, v in parts if k.strip() == "t"]
    sigs = [v.strip() for k, v in parts if k.strip() == "v1"]
    if len(stamps) != 1 or not sigs or not stamps[0].strip().isdigit():
        return False
    t = int(stamps[0])
    if abs((now if now is not None else time.time()) - t) > TOLERANCE_S:
        return False  # replayed or badly delayed
    expected = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def session_status(kind: str, obj: dict) -> str | None:
    """Our payment status for a Checkout Session in this event (or, with kind="", as retrieved)."""
    if kind in EVENTS:
        return EVENTS[kind]
    if kind in ("checkout.session.completed", ""):
        if obj.get("payment_status") in ("paid", "no_payment_required"):
            return "payment.succeeded"  # cards are paid at once
        if obj.get("status") == "expired":
            return "payment.failed"
        if kind:
            return "payment.pending"  # PromptPay completes "unpaid" and pays later (async_payment_*)
    return None


# PaymentIntent events (an endpoint subscribed to these instead of the Checkout ones, staging
# 2026-10-10). They carry our payment id in metadata (set via payment_intent_data at checkout).
INTENT_EVENTS = {"payment_intent.succeeded": "payment.succeeded", "payment_intent.payment_failed": "payment.failed"}


def normalize(event: dict) -> dict | None:
    """A Stripe event as billing.apply_event takes it, or None for events we do not act on."""
    obj = (event.get("data") or {}).get("object") or {}
    kind = event.get("type", "")
    created = event.get("created")
    occurred = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(created)) if created else None
    if obj.get("object") == "payment_intent":
        payment_id = (obj.get("metadata") or {}).get("payment_id")
        if kind not in INTENT_EVENTS or not _is_uuid(payment_id):
            return None  # not one of our checkouts (e.g. a payment made in the dashboard)
        amount = obj.get("amount_received") if kind == "payment_intent.succeeded" else obj.get("amount")
        return {"event_id": str(event["id"]), "type": INTENT_EVENTS[kind], "provider_ref": None,
                "payment_id": str(payment_id), "amount": int(amount or 0),
                "currency": str(obj.get("currency") or "").upper(), "occurred_at": occurred}
    mapped = session_status(kind, obj) if kind else None
    if mapped is None or obj.get("object") != "checkout.session":
        return None
    return {"event_id": str(event["id"]), "type": mapped, "provider_ref": str(obj["id"]),
            "amount": int(obj.get("amount_total") or 0), "currency": str(obj.get("currency") or "").upper(),
            "occurred_at": occurred}


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True
