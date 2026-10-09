"""Billing: plans, checkout, subscription, payments, provider webhooks, sandbox provider (P6, E-45)."""

from __future__ import annotations

import secrets
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, billing, quota
from ..deps import WebAuth, get_db, web_auth
from ..entitlements import entitlement
from ..errors import ApiError, not_found
from ..models import Payment, Plan
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


def payment_out(db: Session, pay: Payment) -> dict:
    plan = db.get(Plan, pay.plan_id)
    return {"id": str(pay.id), "plan": {"code": plan.code, "version": plan.version, "name": plan.name},
            "amount_satang": pay.amount_satang, "currency": pay.currency, "provider": pay.provider,
            "status": pay.status, "applied": pay.applied, "created_at": pay.created_at.isoformat(),
            "succeeded_at": pay.succeeded_at.isoformat() if pay.succeeded_at else None}


class CheckoutIn(BaseModel):
    plan_code: str = Field(max_length=32)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")


class SimulateIn(BaseModel):
    outcome: Literal["succeeded", "failed", "pending", "refunded"]


@router.get("/plans")
def plans(db: Session = Depends(get_db)):
    return {"items": [plan_out(p) for p in billing.purchasable(db)],
            "note": "ราคาเป็นตัวอย่าง ยังไม่อนุมัติ (D05) — ระบบชำระเงินเป็น sandbox เท่านั้น",
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
    sandbox_allowed(request)
    payment, created = billing.checkout(db, auth.workspace_id, auth.user_id, body.plan_code, body.idempotency_key)
    if created:
        audit.record(db, request, "billing.checkout", workspace_id=auth.workspace_id, actor_user_id=auth.user_id,
                     target_id=payment.id)
    db.commit()
    out = payment_out(db, payment) | {"checkout_url": f"/billing/sandbox/{payment.id}"}
    return JSONResponse(out, status_code=201 if created else 200)


@router.get("/payments")
def payments(auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    rows = db.scalars(scoped(Payment, auth.workspace_id).order_by(Payment.created_at.desc()).limit(100)).all()
    return {"items": [payment_out(db, p) for p in rows]}


@router.get("/payments/{payment_id}")
def payment(payment_id: uuid.UUID, auth: WebAuth = Depends(web_auth), db: Session = Depends(get_db)):
    return payment_out(db, get_owned(db, Payment, payment_id, auth.workspace_id))


@router.post("/webhooks/{provider}")
async def webhook(provider: str, request: Request, signature: str | None = Header(default=None, alias="X-Sandbox-Signature"),
                  db: Session = Depends(get_db)):
    """Provider callbacks. The signature is checked over the raw bytes before anything is parsed."""
    if provider != "sandbox":
        raise not_found()
    sandbox_allowed(request)
    body = await request.body()
    if not billing.verify(sandbox_secret(request), body, signature):
        raise ApiError(400, "INVALID_SIGNATURE", "ลายเซ็นไม่ถูกต้อง")
    result = billing.handle_event(db, provider, body)
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
