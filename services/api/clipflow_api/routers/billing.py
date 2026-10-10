"""Billing: plans, checkout, subscription, payments, provider webhooks, sandbox provider (P6, E-45)."""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, billing, quota
from .. import stripe_provider as stripe
from ..deps import WebAuth, get_db, web_auth
from ..entitlements import default_plan, entitlement
from ..errors import ApiError, not_found
from ..models import Payment, Plan, User
from ..tenancy import get_owned, scoped

router = APIRouter(prefix="/v1/billing")


def sandbox_secret(request: Request) -> bytes:
    state = request.app.state
    if not getattr(state, "billing_secret", None):
        configured = state.settings.billing_sandbox_secret.encode()
        state.billing_secret = configured or secrets.token_bytes(32)
    return state.billing_secret


def sandbox_allowed(request: Request) -> None:
    if request.app.state.settings.app_env == "production":
        raise not_found()  # no sandbox money on a production server


def plan_out(p: Plan) -> dict:
    return {"code": p.code, "version": p.version, "name": p.name, "price_satang": p.price_satang,
            "currency": p.currency, "interval_days": p.interval_days, "example_price": p.is_demo,
            "limits": {"registered_agents": p.max_registered_agents, "concurrent_sessions": p.max_concurrent_sessions,
                       "devices": p.max_devices, "clips_per_cycle": p.clips_per_month}}


def trial_out(db: Session, version: int | None = None) -> dict:
    """What a new Workspace gets (the latest trial version), for the landing page and the plan list."""
    p = default_plan(db, version)
    return {"days": p.interval_days, "clips": p.clips_per_month, "devices": p.max_devices,
            "registered_agents": p.max_registered_agents, "price_satang": p.price_satang}


def payment_out(db: Session, pay: Payment) -> dict:
    plan = db.get(Plan, pay.plan_id)
    return {"id": str(pay.id), "plan": {"code": plan.code, "version": plan.version, "name": plan.name},
            "amount_satang": pay.amount_satang, "currency": pay.currency, "provider": pay.provider,
            "status": pay.status, "applied": pay.applied, "created_at": pay.created_at.isoformat(),
            "succeeded_at": pay.succeeded_at.isoformat() if pay.succeeded_at else None}


def provider(request: Request) -> str:
    """The payment provider this server uses (D06): "stripe" only with an allowed key and a webhook secret."""
    s = request.app.state.settings
    if s.billing_provider != "stripe":
        return "sandbox"
    if not (stripe.key_allowed(s.stripe_secret_key, s.app_env) and s.stripe_webhook_secret):
        raise ApiError(503, "PAYMENTS_NOT_READY", "ระบบชำระเงินยังตั้งค่าไม่ครบ ติดต่อทีมงาน")
    return "stripe"


def provider_note(request: Request) -> str:
    s = request.app.state.settings
    if s.billing_provider == "stripe":
        if stripe.test_mode(s.stripe_secret_key):
            return "ชำระผ่าน Stripe (โหมดทดสอบ) — ยังไม่ตัดเงินจริง ใช้บัตรทดสอบของ Stripe"
        return "ชำระผ่าน Stripe (บัตร / PromptPay)"
    return "ระบบชำระเงินยังเป็น sandbox — ยังไม่รับเงินจริง (G6-01/G6-02)"


class CheckoutIn(BaseModel):
    plan_code: str = Field(max_length=32)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")


class SimulateIn(BaseModel):
    outcome: Literal["succeeded", "failed", "pending", "refunded"]


@router.get("/plans")
def plans(request: Request, db: Session = Depends(get_db)):
    return {"items": [plan_out(p) for p in billing.purchasable(db)],
            "trial": trial_out(db, request.app.state.settings.default_plan_version),
            "note": provider_note(request),
            "refund_policy": "ไม่คืนเงินทุกกรณี"}


@router.get("/subscription")
def subscription(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    ent = entitlement(db, auth.workspace_id)
    c = ent.cycle
    return {"status": c.status, "plan": plan_out(c.plan), "cycle_start": c.start.isoformat(),
            "cycle_end": c.end.isoformat(), "paid_cycles_ahead": c.paid_cycles_ahead,
            "next_plan": plan_out(c.next_plan) if c.next_plan else None,
            "quota": quota.summary(db, auth.workspace_id, billing.now())}


@router.post("/checkout")
def checkout(body: CheckoutIn, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    via = provider(request)
    if via == "sandbox":
        sandbox_allowed(request)
    payment, created = billing.checkout(db, auth.workspace_id, auth.user_id, body.plan_code, body.idempotency_key,
                                        provider=via)
    if created:
        audit.record(db, request, "billing.checkout", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                     target_id=payment.id, details={"provider": via})
    if payment.provider == "sandbox":
        db.commit()
        out = payment_out(db, payment) | {"checkout_url": f"/billing/sandbox/{payment.id}"}
        return JSONResponse(out, status_code=201 if created else 200)
    # Stripe Checkout: the payment id is the idempotency key, so a repeat returns the same Session
    s = request.app.state.settings
    plan = db.get(Plan, payment.plan_id)
    back = f"{s.web_origin.rstrip('/')}/billing?payment={payment.id}"
    try:
        session = stripe.create_checkout(
            s.stripe_secret_key, payment_id=str(payment.id), amount_satang=payment.amount_satang,
            currency=payment.currency, product=f"punpun {plan.name} ({plan.interval_days} วัน)",
            success_url=back, cancel_url=f"{back}&cancelled=1", email=db.get(User, auth.user_id).email)
    except stripe.StripeError as exc:
        db.rollback()
        raise ApiError(502, "PAYMENT_PROVIDER_UNAVAILABLE", "ติดต่อระบบชำระเงินไม่ได้ ลองใหม่อีกครั้ง",
                       {"detail": str(exc)[:200]}) from None
    payment.provider_ref = session["id"]  # webhooks name the Session; nothing else ties them to us
    db.commit()
    out = payment_out(db, payment) | {"checkout_url": session["url"]}
    return JSONResponse(out, status_code=201 if created else 200)


@router.get("/payments")
def payments(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    rows = db.scalars(scoped(Payment, auth.workspace_id).order_by(Payment.created_at.desc()).limit(100)).all()
    return {"items": [payment_out(db, p) for p in rows]}


@router.get("/payments/{payment_id}")
def payment(payment_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    return payment_out(db, get_owned(db, Payment, payment_id, auth.workspace_id))


@router.post("/payments/{payment_id}/refresh")
def refresh(payment_id: uuid.UUID, request: Request, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    """A pending Stripe payment, asked of Stripe directly (our secret key, HTTPS): settles it when the
    webhook has not arrived, and gives the Stripe page back while it is still open. The result goes
    through billing.apply_event like a webhook (once per payment and outcome, forward-only, amount
    must match), so a later webhook for the same payment changes nothing."""
    pay = get_owned(db, Payment, payment_id, auth.workspace_id)
    if pay.provider != "stripe" or pay.status != "pending":
        return payment_out(db, pay) | {"checkout_url": None}
    provider(request)  # 503 when Stripe is not set up on this server
    s = request.app.state.settings
    try:
        session = stripe.retrieve_checkout(s.stripe_secret_key, pay.provider_ref)
    except stripe.StripeError as exc:
        raise ApiError(502, "PAYMENT_PROVIDER_UNAVAILABLE", "ติดต่อระบบชำระเงินไม่ได้ ลองใหม่อีกครั้ง",
                       {"detail": str(exc)[:200]}) from None
    target = stripe.session_status("", session)
    if target:
        event = {"event_id": f"retrieve:{pay.id}:{target}", "type": target, "provider_ref": str(session.get("id")),
                 "amount": int(session.get("amount_total") or 0),
                 "currency": str(session.get("currency") or "").upper(), "occurred_at": None}
        billing.apply_event(db, "stripe", event, json.dumps(session, sort_keys=True).encode())
        db.commit()
        db.refresh(pay)
    url = session.get("url") if session.get("status") == "open" else None
    return payment_out(db, pay) | {"checkout_url": url}


@router.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request, signature: str | None = Header(default=None, alias="X-Sandbox-Signature"),
                  db: Session = Depends(get_db)):
    """Provider callbacks. The signature is checked over the raw bytes before anything is parsed."""
    if provider == "stripe":
        return await stripe_webhook(request, db)
    if provider != "sandbox":
        raise not_found()
    sandbox_allowed(request)
    body = await request.body()
    if not billing.verify(sandbox_secret(request), body, signature):
        raise ApiError(400, "INVALID_SIGNATURE", "ลายเซ็นไม่ถูกต้อง")
    result = billing.handle_event(db, provider, body)
    db.commit()
    return result


async def stripe_webhook(request: Request, db: Session) -> dict:
    s = request.app.state.settings
    if s.billing_provider != "stripe" or not s.stripe_webhook_secret:
        raise not_found()
    body = await request.body()
    if not stripe.verify(s.stripe_webhook_secret, body, request.headers.get("Stripe-Signature")):
        raise ApiError(400, "INVALID_SIGNATURE", "ลายเซ็นไม่ถูกต้อง")
    try:
        event = stripe.normalize(json.loads(body))
    except (KeyError, TypeError, ValueError):
        raise ApiError(400, "BAD_EVENT", "รูปแบบ event ไม่ถูกต้อง") from None
    if event is None:
        return {"ignored": True}  # an event we do not act on: 200, so Stripe does not keep resending it
    result = billing.apply_event(db, "stripe", event, body)
    db.commit()
    return result


@router.post("/sandbox/{payment_id}/simulate")
def simulate(payment_id: uuid.UUID, body: SimulateIn, request: Request, auth: WebAuth = Depends(web_auth),
             db: Session = Depends(get_db)):
    """The sandbox provider's own page: it sends the signed event a real provider would send. The
    result reaches the subscription only through the webhook handler, like a real payment."""
    sandbox_allowed(request)
    pay = get_owned(db, Payment, payment_id, auth.workspace_id)
    raw, sig = billing.sandbox_event(sandbox_secret(request), pay, body.outcome)
    if not billing.verify(sandbox_secret(request), raw, sig):  # same path as an external delivery
        raise ApiError(500, "SANDBOX_SIGNATURE", "sandbox signing failed")
    result = billing.handle_event(db, "sandbox", raw)
    db.commit()
    return result | {"payment": payment_out(db, db.scalars(select(Payment).where(Payment.id == pay.id)).one())}
