"""G6-05: platform staff, audit with reasons and before/after, support read-only, retention lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from api_test_shop import FULL_DAY, set_times
from sqlalchemy import select, update

from clipflow_api import manage
from clipflow_api.models import AuditEvent, Clip, User


def make_staff(app, acc, role):
    with app.state.db.sessionmaker() as s:
        assert manage.grant_role(s, acc.email, role) == 0


def ws_id(acc):
    return acc.body["workspace"]["id"]


def test_admin_routes_do_not_exist_for_customers(onboard):
    customer = onboard()
    assert customer.get("/v1/admin/me").status_code == 404
    assert customer.get("/v1/admin/workspaces").status_code == 404
    assert customer.post(f"/v1/admin/workspaces/{ws_id(customer)}/extend",
                         json={"days": 30, "reason": "x" * 20}).status_code == 404
    assert customer.get("/v1/me").json()["user"]["platform_role"] is None


def test_support_reads_and_cannot_change(onboard, app):
    support, customer = onboard(), onboard()
    make_staff(app, support, "support")
    assert support.get("/v1/admin/me").json() == {"role": "support"}
    found = support.get("/v1/admin/workspaces", params={"q": customer.username}).json()["items"]
    assert [w["id"] for w in found] == [ws_id(customer)]
    detail = support.get(f"/v1/admin/workspaces/{ws_id(customer)}").json()
    assert detail["subscription"]["status"] == "trial" and "quota" in detail
    for path, body in [(f"/v1/admin/workspaces/{ws_id(customer)}/extend", {"days": 30, "reason": "x" * 20}),
                       (f"/v1/admin/workspaces/{ws_id(customer)}/quota",
                        {"units": 5, "reason": "x" * 20, "idempotency_key": uuid.uuid4().hex}),
                       ("/v1/admin/retention", {"reason": "x" * 20})]:
        assert support.post(path, json=body).json()["code"] == "ADMIN_ONLY"
    assert support.get("/v1/admin/payments").status_code == 403


def test_admin_changes_need_a_reason_and_are_audited_with_before_after(onboard, app):
    admin, customer = onboard(), onboard()
    make_staff(app, admin, "admin")
    short = admin.post(f"/v1/admin/workspaces/{ws_id(customer)}/extend", json={"days": 30, "reason": "too short"})
    assert short.status_code == 422
    before = customer.get("/v1/billing/subscription").json()
    out = admin.post(f"/v1/admin/workspaces/{ws_id(customer)}/extend",
                     json={"days": 14, "reason": "ทดลองต่อให้ลูกค้า pilot ตามที่ PO อนุมัติ"}).json()
    after = customer.get("/v1/billing/subscription").json()
    assert datetime.fromisoformat(after["cycle_end"]) - datetime.fromisoformat(before["cycle_end"]) == timedelta(days=14)
    entry = out["audit"][0]
    assert entry["action"] == "admin.subscription.extend" and entry["reason"].startswith("ทดลองต่อ")
    assert entry["details"]["before"]["cycle_end"] == before["cycle_end"] and entry["details"]["days"] == 14

    admin.post(f"/v1/admin/workspaces/{ws_id(customer)}/plan",
               json={"plan_code": "business", "when": "now", "reason": "อัปเกรดทดสอบตามคำขอ support #12"})
    assert customer.get("/v1/billing/subscription").json()["plan"]["code"] == "business"
    with app.state.db.sessionmaker() as s:
        rows = s.scalars(select(AuditEvent).where(AuditEvent.workspace_id == uuid.UUID(ws_id(customer)),
                                                  AuditEvent.action.like("admin.%"))).all()
        actors = {str(r.actor_user_id) for r in rows}
    assert actors == {str(admin.user_id)} and len(rows) == 2


def test_quota_adjustment_is_counted_once(onboard, app):
    admin, customer = onboard(), onboard()
    make_staff(app, admin, "admin")
    key = uuid.uuid4().hex
    body = {"units": -5, "reason": "หักโควตาที่ใช้ผิดพลาดจากเหตุ #7", "idempotency_key": key}
    first = admin.post(f"/v1/admin/workspaces/{ws_id(customer)}/quota", json=body).json()
    again = admin.post(f"/v1/admin/workspaces/{ws_id(customer)}/quota", json=body).json()
    assert first["applied"] and not again["applied"]
    assert customer.get("/v1/billing/subscription").json()["quota"]["used"] == 5
    admin.post(f"/v1/admin/workspaces/{ws_id(customer)}/quota",
               json={"units": 8, "reason": "คืนโควตาชดเชยระบบล่ม #8", "idempotency_key": uuid.uuid4().hex})
    assert customer.get("/v1/billing/subscription").json()["quota"]["available"] == 33  # 30 - 5 + 8


def test_new_plan_version_never_edits_a_paid_one(onboard, app):
    admin, customer = onboard(), onboard()
    make_staff(app, admin, "admin")
    pay = customer.post("/v1/billing/checkout", json={"plan_code": "pro", "idempotency_key": uuid.uuid4().hex}).json()
    customer.post(f"/v1/billing/sandbox/{pay['id']}/simulate", json={"outcome": "succeeded"})
    out = admin.post("/v1/admin/plans/pro/versions",
                     json={"price_satang": 129000, "clips_per_month": 200, "reason": "ตั้งราคาจริงตาม D05 (ทดสอบ)"}).json()
    assert out == {"code": "pro", "version": 2}
    assert customer.get("/v1/billing/subscription").json()["plan"]["version"] == 1  # keeps what was paid
    offered = {p["code"]: p for p in customer.get("/v1/billing/plans").json()["items"]}
    assert offered["pro"]["version"] == 2 and offered["pro"]["price_satang"] == 129000
    assert admin.get("/v1/admin/payments").json()["items"][0]["status"] == "succeeded"  # history kept
    # The plan catalog is shared by every test in the session: put the example price back (version 3).
    admin.post("/v1/admin/plans/pro/versions",
               json={"price_satang": 99000, "clips_per_month": 150, "reason": "คืนราคาตัวอย่างหลังทดสอบ"})


def test_retention_deletes_old_files_but_never_ones_still_needed(shop, onboard, app, storage):
    admin = onboard()
    make_staff(app, admin, "admin")
    old_job, old_clips = shop.job(clips=1)  # finished, nothing scheduled
    busy_job, busy_clips = shop.job(clips=1)  # finished, but scheduled to post
    shop.create(busy_job, **FULL_DAY)
    with app.state.db.sessionmaker() as s:
        s.execute(update(Clip).where(Clip.id.in_([uuid.UUID(old_clips[0]), uuid.UUID(busy_clips[0])]))
                  .values(uploaded_at=datetime.now(UTC) - timedelta(days=45)))
        s.commit()
        old_key = s.get(Clip, uuid.UUID(old_clips[0])).storage_key
    dry = admin.post("/v1/admin/retention", json={"reason": "ทดสอบรอบเก็บไฟล์ 30 วัน", "dry_run": True}).json()
    assert old_clips[0] in dry["deleted"] and busy_clips[0] in dry["kept_in_use"] and storage.exists(old_key)
    real = admin.post("/v1/admin/retention", json={"reason": "ทดสอบรอบเก็บไฟล์ 30 วัน", "dry_run": False}).json()
    assert old_clips[0] in real["deleted"] and busy_clips[0] in real["kept_in_use"]
    assert not storage.exists(old_key)
    gone = shop.acc.get(f"/v1/clips/{old_clips[0]}/media")
    assert gone.status_code == 410 and gone.json()["code"] == "CLIP_FILE_EXPIRED"
    assert shop.acc.get(f"/v1/clips/{busy_clips[0]}/media").status_code == 200
    clip = shop.acc.get(f"/v1/clips/{old_clips[0]}").json()
    assert clip["render_sha256"] and clip["approval"]["approved"]  # history and approval stay


def test_roles_are_granted_only_on_the_server(onboard, app):
    acc = onboard()
    assert acc.patch("/v1/me", json={"platform_role": "admin"}).status_code in (404, 405)
    make_staff(app, acc, "admin")
    make_staff(app, acc, "none")
    with app.state.db.sessionmaker() as s:
        assert s.get(User, acc.user_id).platform_role is None
        trail = s.scalars(select(AuditEvent).where(AuditEvent.action == "platform_role.set",
                                                   AuditEvent.target_id == acc.user_id)).all()
    assert [t.details["after"] for t in trail] == ["admin", None]
    assert acc.get("/v1/admin/me").status_code == 404
    set_times  # noqa: B018 - imported helper kept for symmetry with other suites
