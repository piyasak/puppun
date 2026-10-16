"""Phone screen diagnostics (PO 2026-10-16): screenshots and screen readings from the Agent, viewed on the web.

Nobody can reach a customer's Agent from outside (outbound HTTPS only, no exposed ADB), so when TikTok
shows something the Agent does not expect, nobody could see it. Now:
- on failure: when a post stops on a TikTok screen (NEEDS_ACTION / UNKNOWN), the Agent uploads what it
  saw at that moment (a PNG screenshot and the screen reading as XML), tied to the post;
- on request: the Workspace owner (or a platform admin) asks for a check of one phone; the Agent, when
  the phone is free, runs read-only steps (CHECKS) and uploads each screen.

Screenshots can show other people's content and the account's data, so: stored privately, shown only to
the Workspace's members and platform staff through short-lived links, every view audited, and deleted
after KEEP_DAYS (`purge`, run on every diagnostics call and with retention).
"""

from __future__ import annotations

import contextlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import devices as device_rules
from .errors import ApiError
from .models import Device, Diagnostic, ScheduleItem

KEEP_DAYS = 7
MAX_FILE_BYTES = {"png": 4_000_000, "xml": 3_000_000}
MAX_FILES = 16
# What the Agent may be asked to look at (read-only steps; agent/diagnostics.py runs them).
CHECKS = {
    "profile": "หน้าโปรไฟล์",
    "newest_public_video": "วิดีโอสาธารณะล่าสุด",
    "newest_private_video": "วิดีโอส่วนตัวล่าสุด",
}
OPEN = ("requested", "running")
NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def now() -> datetime:
    return datetime.now(UTC)


def purge(db: Session, storage, at: datetime | None = None) -> int:
    """Delete diagnostics past their keep date, files first."""
    at = at or now()
    old = db.scalars(select(Diagnostic).where(Diagnostic.expires_at < at).limit(200)).all()
    for row in old:
        for f in row.files or []:
            with contextlib.suppress(Exception):  # a missing file must not keep the row
                storage.delete(f["key"])
        db.delete(row)
    return len(old)


def _device(db: Session, environment_id: uuid.UUID, serial: str) -> Device:
    key = device_rules.normalize_serial(serial)[1]
    device = db.scalars(select(Device).where(Device.environment_id == environment_id, Device.serial_key == key,
                                             Device.unbound_at.is_(None))).first()
    if device is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบโทรศัพท์นี้ใน Environment นี้")
    return device


def request(db: Session, workspace_id: uuid.UUID, device_id: uuid.UUID, check: str, user_id: uuid.UUID) -> Diagnostic:
    if check not in CHECKS:
        raise ApiError(422, "VALIDATION_ERROR", "ไม่รู้จักการตรวจนี้", {"check": check})
    device = db.scalars(select(Device).where(Device.id == device_id, Device.workspace_id == workspace_id)).first()
    if device is None or device.unbound_at is not None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบโทรศัพท์นี้")
    if db.scalars(select(Diagnostic).where(Diagnostic.device_id == device.id, Diagnostic.status.in_(OPEN))).first():
        raise ApiError(409, "DIAGNOSTIC_OPEN", "มีการตรวจหน้าจอของโทรศัพท์นี้ที่ยังไม่เสร็จ")
    at = now()
    row = Diagnostic(workspace_id=workspace_id, device_id=device.id, kind="on_request", check=check,
                     status="requested", requested_by=user_id, files=[], expires_at=at + timedelta(days=KEEP_DAYS))
    db.add(row)
    db.flush()
    return row


def failure(db: Session, environment_id: uuid.UUID, serial: str, item_id: uuid.UUID | None, code: str) -> Diagnostic:
    """The Agent's capture when a post stopped on a TikTok screen."""
    device = _device(db, environment_id, serial)
    if item_id is not None:
        item = db.get(ScheduleItem, item_id)
        if item is None or item.device_id != device.id:
            raise ApiError(404, "NOT_FOUND", "ไม่พบรายการนี้")
    at = now()
    row = Diagnostic(workspace_id=device.workspace_id, device_id=device.id, item_id=item_id, kind="failure",
                     check=None, code=(code or "")[:40] or None, status="running", files=[],
                     expires_at=at + timedelta(days=KEEP_DAYS))
    db.add(row)
    db.flush()
    return row


def next_requested(db: Session, environment_id: uuid.UUID, serials: list[str]) -> Diagnostic | None:
    keys = set()
    for raw in serials[:50]:
        try:
            keys.add(device_rules.normalize_serial(raw)[1])
        except ApiError:
            continue
    if not keys:
        return None
    row = db.scalars(select(Diagnostic).join(Device, Device.id == Diagnostic.device_id).where(
        Device.environment_id == environment_id, Device.serial_key.in_(keys), Device.unbound_at.is_(None),
        Diagnostic.status == "requested").order_by(Diagnostic.created_at).limit(1)
        .with_for_update(of=Diagnostic, skip_locked=True)).first()
    if row is not None:
        row.status, row.started_at = "running", now()
    return row


def agent_row(db: Session, environment_id: uuid.UUID, diag_id: uuid.UUID) -> Diagnostic:
    row = db.scalars(select(Diagnostic).join(Device, Device.id == Diagnostic.device_id).where(
        Diagnostic.id == diag_id, Device.environment_id == environment_id).with_for_update(of=Diagnostic)).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "ไม่พบการตรวจนี้")
    if row.status != "running":
        raise ApiError(409, "DIAGNOSTIC_CLOSED", "การตรวจนี้ปิดแล้ว")
    return row


def add_file(row: Diagnostic, storage, step: int, name: str, ext: str, temp: Path, size: int) -> None:
    if ext not in MAX_FILE_BYTES or not NAME_RE.match(name) or not 0 <= step < 50:
        raise ApiError(422, "VALIDATION_ERROR", "ชื่อไฟล์การตรวจไม่ถูกต้อง")
    if len(row.files or []) >= MAX_FILES:
        raise ApiError(409, "DIAGNOSTIC_FULL", "ไฟล์ของการตรวจนี้ครบแล้ว")
    if ext == "png" and not temp.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n":
        raise ApiError(422, "VALIDATION_ERROR", "ไม่ใช่ไฟล์ PNG")
    key = f"diagnostics/{row.workspace_id}/{row.id}/{step:02d}_{name}.{ext}"
    storage.put_file(key, temp, "image/png" if ext == "png" else "text/plain")
    row.files = [*(row.files or []), {"step": step, "name": name, "kind": ext, "key": key, "bytes": size}]


def finish(row: Diagnostic, note: str | None, error: str | None) -> None:
    row.status = "failed" if error else "done"
    row.note = (error or note or "")[:300] or None
    row.completed_at = now()


def out(row: Diagnostic, storage=None, ttl_s: int = 600) -> dict:
    files = []
    for f in sorted(row.files or [], key=lambda f: (f["step"], f["kind"])):
        item = {"step": f["step"], "name": f["name"], "kind": f["kind"], "bytes": f.get("bytes")}
        if storage is not None:
            item["url"] = storage.preview_url(f["key"], ttl_s)
        files.append(item)
    return {"id": str(row.id), "device_id": str(row.device_id), "item_id": str(row.item_id) if row.item_id else None,
            "kind": row.kind, "check": row.check, "check_label": CHECKS.get(row.check or ""), "code": row.code,
            "status": row.status, "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "expires_at": row.expires_at.isoformat(), "files": files}
