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
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.stripe.com/v1"
TOLERANCE_S = 300

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
    data = urllib.parse.urlencode(_form(params)).encode()
    auth = base64.b64encode(f"{secret_key}:".encode()).decode()
    req = urllib.request.Request(f"{API}/checkout/sessions", data=data, method="POST", headers={
        "Authorization": f"Basic {auth}", "Idempotency-Key": f"checkout-{payment_id}",
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(req, timeout=20) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read()).get("error", {}).get("message", "")
        except ValueError:
            message = ""
        raise StripeError(f"Stripe {exc.code}: {message[:200]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise StripeError(f"Stripe unreachable: {exc}") from None
    return {"id": body["id"], "url": body["url"]}


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


def normalize(event: dict) -> dict | None:
    """A Stripe event as billing.apply_event takes it, or None for events we do not act on."""
    kind = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}
    if kind == "checkout.session.completed":
        # Cards are paid at once; PromptPay completes "unpaid" and pays later (async_payment_*)
        mapped = "payment.succeeded" if obj.get("payment_status") == "paid" else "payment.pending"
    else:
        mapped = EVENTS.get(kind)
    if mapped is None or obj.get("object") != "checkout.session":
        return None
    created = event.get("created")
    return {"event_id": str(event["id"]), "type": mapped, "provider_ref": str(obj["id"]),
            "amount": int(obj.get("amount_total") or 0), "currency": str(obj.get("currency") or "").upper(),
            "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(created)) if created else None}
