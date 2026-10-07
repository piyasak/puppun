"""Device registration through the Agent (FR-15, G2-04, architecture §2.4).

- The serial identifies a phone but proves nothing: anyone can type one. A serial already bound
  (active) anywhere is refused with one generic conflict — never moved, and the answer does not
  say who owns it (T07).
- The Agent must send the phone's hardware serial (`ro.serialno`). ADB-over-Wi-Fi transport ids
  (`ip:port`, mDNS names) change between connections, so they are rejected as identifiers.
- Only phones the Agent sees in the ready `device` state can be registered; unauthorized or
  offline phones are reported so the web can tell the user what to do.
- Device caps are per Environment (allocated from the plan, P2.3), checked under the
  Environment row lock; the partial unique index settles cross-Workspace races.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .agent_sessions import AgentContext, now
from .errors import ApiError
from .models import Device, Environment

SERIAL_RE = re.compile(r"^[A-Za-z0-9._-]{4,64}$")
ADB_STATES = {"device", "unauthorized", "offline", "missing"}


def normalize_serial(raw: str) -> tuple[str, str]:
    """Return (serial as reported, comparison key). Raises 422 for unusable serials."""
    serial = (raw or "").strip()
    if ":" in serial or "_adb-tls-connect" in serial or "._tcp" in serial:
        raise ApiError(422, "SERIAL_NOT_STABLE",
                       "ใช้ Serial ของเครื่อง (ro.serialno) ไม่ใช่ที่อยู่ ADB ผ่าน Wi-Fi ซึ่งเปลี่ยนได้")
    if not SERIAL_RE.match(serial):
        raise ApiError(422, "SERIAL_INVALID", "Serial ไม่ถูกต้อง")
    return serial, serial.lower()


def ownership_conflict() -> ApiError:
    return ApiError(409, "DEVICE_OWNERSHIP_CONFLICT",
                    "โทรศัพท์เครื่องนี้ถูกผูกกับบัญชีหรือ Environment อื่นอยู่แล้ว "
                    "ต้องให้เจ้าของเดิมยกเลิกการผูกก่อน หรือติดต่อฝ่ายช่วยเหลือ")


def active_count(db: Session, environment_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Device).where(
        Device.environment_id == environment_id, Device.unbound_at.is_(None)))


def register(db: Session, ctx: AgentContext, raw_serial: str, adb_state: str,
             model: str | None, android_version: str | None) -> tuple[Device, bool]:
    """Bind a ready phone to the session's Environment. Returns (device, created)."""
    serial, key = normalize_serial(raw_serial)
    if adb_state != "device":
        hint = {"unauthorized": "กด \"อนุญาต\" (Allow USB debugging) บนหน้าจอโทรศัพท์",
                "offline": "ถอดสาย USB แล้วเสียบใหม่ หรือรีสตาร์ทโทรศัพท์"}.get(adb_state, "ตรวจการเชื่อมต่อ USB")
        raise ApiError(409, "DEVICE_NOT_READY", f"โทรศัพท์ยังไม่พร้อม ({adb_state}): {hint}", {"adb_state": adb_state})

    env = db.scalars(select(Environment).where(Environment.id == ctx.environment_id).with_for_update()).one()
    at = now()
    existing = db.scalars(select(Device).where(Device.serial_key == key, Device.unbound_at.is_(None))).first()
    if existing is not None:
        if existing.environment_id != env.id:
            raise ownership_conflict()  # other Environment or other Workspace: same answer
        existing.model = (model or existing.model or "")[:64] or None
        existing.android_version = (android_version or existing.android_version or "")[:16] or None
        existing.last_state, existing.last_reported_at = "device", at
        return existing, False

    if active_count(db, env.id) >= env.device_limit:
        raise ApiError(409, "DEVICE_LIMIT_REACHED",
                       "Environment นี้ผูกโทรศัพท์ครบตามจำนวนแล้ว ยกเลิกการผูกเครื่องที่ไม่ใช้ในหน้าเว็บก่อน",
                       {"limit": env.device_limit})
    device = Device(
        workspace_id=env.workspace_id, environment_id=env.id, serial=serial, serial_key=key,
        model=(model or "")[:64] or None, android_version=(android_version or "")[:16] or None,
        registered_by=ctx.installation_ref, last_state="device", last_reported_at=at,
    )
    db.add(device)
    try:
        db.flush()
    except IntegrityError:  # another Workspace bound the same serial at the same moment
        db.rollback()
        raise ownership_conflict() from None
    return device, True


def report(db: Session, ctx: AgentContext, states: dict[str, str]) -> int:
    """Record what the Agent currently sees for phones bound to its Environment.

    Bound phones the Agent no longer sees become `missing`. Serials of phones bound elsewhere
    are ignored without comment (no information about other owners).
    """
    at = now()
    keys = {}
    for raw, state in states.items():
        try:
            keys[normalize_serial(raw)[1]] = state if state in ADB_STATES else "offline"
        except ApiError:
            continue
    rows = db.scalars(select(Device).where(Device.environment_id == ctx.environment_id,
                                           Device.unbound_at.is_(None))).all()
    for d in rows:
        d.last_state = keys.get(d.serial_key, "missing")
        d.last_reported_at = at
    return len(rows)


def missing_details(device: Device) -> list[str]:
    """Owner-entered fields still empty. The phone cannot be scheduled for posting until the
    expected TikTok account is set (FR-16); the display name is for the owner's convenience."""
    missing = []
    if not device.display_name:
        missing.append("display_name")
    if not device.expected_account:
        missing.append("expected_account")
    return missing


def readiness(device: Device, agent_online: bool) -> str:
    """ready / unauthorized / offline / missing / agent_offline / unknown for the web UI."""
    if device.unbound_at is not None:
        return "unbound"
    if not agent_online:
        return "agent_offline"
    return {"device": "ready", None: "unknown"}.get(device.last_state, device.last_state)
