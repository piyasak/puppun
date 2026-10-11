"""Find phones over ADB and register the ready ones with the server (FR-15, P2.6).

The server identifies a phone by its hardware serial (`ro.serialno`), not by the ADB
transport id: an ADB-over-Wi-Fi id (`ip:port`) changes between connections. Phones that are
not ready (unauthorized/offline) are reported with a hint instead of being registered.
Read-only on the phone: only `getprop` and `pm list packages` (is the Thai keyboard there, Q-44).
"""

from __future__ import annotations

from dataclasses import dataclass

from agent import thai_keyboard
from agent.adb import Adb, AdbError, is_wireless_serial


@dataclass(frozen=True)
class SeenPhone:
    adb_serial: str  # what `adb devices` shows (transport id)
    hw_serial: str | None  # ro.serialno; None when the phone cannot be queried
    state: str  # device | unauthorized | offline | ...
    model: str | None = None
    android_version: str | None = None
    thai_keyboard: bool | None = None  # a Thai keyboard installed (needed for live posts); None = not read


def discover(adb: Adb) -> list[SeenPhone]:
    phones = []
    for entry in adb.devices():
        if entry.ready:
            hw = adb.shell(entry.serial, "getprop ro.serialno").strip() or None
            model = adb.shell(entry.serial, "getprop ro.product.model").strip() or entry.model
            release = adb.shell(entry.serial, "getprop ro.build.version.release").strip() or None
            try:
                keyboard = thai_keyboard.installed(adb, entry.serial)
            except AdbError:
                keyboard = None
            phones.append(SeenPhone(entry.serial, hw, entry.state, model, release, keyboard))
        else:
            # Over USB the transport id is the hardware serial; over Wi-Fi it is not usable.
            hw = None if is_wireless_serial(entry.serial) else entry.serial
            phones.append(SeenPhone(entry.serial, hw, entry.state, entry.model))
    return phones


def report_map(phones: list[SeenPhone]) -> dict[str, str]:
    return {p.hw_serial: p.state for p in phones if p.hw_serial}


def register_ready(client, session, phones: list[SeenPhone], only: str | None = None) -> list[dict]:
    """Register every ready phone (or just `only`), then report all states. Returns one result per phone."""
    from agent.server_client import ServerError

    results = []
    for p in phones:
        if only and only.lower() not in (p.adb_serial.lower(), (p.hw_serial or "").lower()):
            continue
        if p.hw_serial is None:
            results.append({"adb_serial": p.adb_serial, "state": p.state, "outcome": "SERIAL_UNAVAILABLE"})
            continue
        try:
            body = client.register_device(session, p.hw_serial, p.state, p.model, p.android_version,
                                          p.thai_keyboard)
            outcome = "REGISTERED" if body.get("created") else "ALREADY_REGISTERED"
            results.append({"serial": p.hw_serial, "state": p.state, "outcome": outcome, "device_id": body["id"],
                            "model": p.model, "display_name": body.get("display_name"),
                            "expected_account": body.get("expected_account"),
                            "missing_details": body.get("missing_details", []),
                            "details_url": body.get("details_url"), "thai_keyboard": p.thai_keyboard})
        except ServerError as exc:
            results.append({"serial": p.hw_serial, "state": p.state, "outcome": exc.code, "message": exc.message,
                            "model": p.model})
    client.report_devices(session, report_map(phones))
    return results


def describe(result: dict) -> str:
    """One Thai line per phone for the Agent's console / local status UI (Q-25)."""
    line = _describe(result)
    if result["outcome"] in ("REGISTERED", "ALREADY_REGISTERED") and result.get("thai_keyboard") is False:
        line += (" — ยังไม่มีคีย์บอร์ดพิมพ์ไทย (punpun Thai input) จึงโพสต์จริงไม่ได้: "
                 "เปิดหน้าต่างตั้งค่า Agent แล้วกด \"ติดตั้งคีย์บอร์ดพิมพ์ไทย\"")
    return line


def _describe(result: dict) -> str:
    name = result.get("display_name") or result.get("model") or "โทรศัพท์"
    serial = result.get("serial") or result.get("adb_serial") or "?"
    phone = f"{name} ({serial})"
    outcome = result["outcome"]
    url = result.get("details_url")
    if outcome == "REGISTERED":
        return f"ลงทะเบียนโทรศัพท์ {phone} แล้ว — กรุณาไปใส่รายละเอียด (ชื่อเรียกเครื่อง, บัญชี TikTok) ที่ {url}"
    if outcome == "ALREADY_REGISTERED":
        if result.get("missing_details"):
            return f"โทรศัพท์ {phone} ลงทะเบียนไว้แล้ว แต่ยังไม่ได้ใส่รายละเอียด — กรุณาไปใส่ที่ {url}"
        return f"โทรศัพท์ {phone} พร้อมใช้งาน (บัญชี TikTok @{result.get('expected_account')})"
    if outcome == "SERIAL_UNAVAILABLE":
        return f"โทรศัพท์ {phone} เชื่อมผ่าน ADB แบบ Wi-Fi ใช้ลงทะเบียนไม่ได้ — กรุณาเสียบสาย USB"
    return f"โทรศัพท์ {phone}: {result.get('message') or outcome}"


class DeviceSync:
    """Phone check on Agent start and every minute while it runs (Q-25).

    Each call reads the phones over ADB, registers the ready ones the server does not know
    yet, and reports every phone's state. Only changes are announced, so the console is not
    flooded every minute. Never raises: a missing `adb` or a server refusal becomes a message.
    """

    def __init__(self, adb_factory, log=print):
        self._adb_factory = adb_factory
        self._log = log
        self._last: dict[str, str] = {}  # serial -> last announced outcome/state
        self._adb = None
        self.announced_empty = False

    def __call__(self, client, session) -> list[dict]:
        from agent.adb import AdbError
        from agent.server_client import ServerError

        try:
            if self._adb is None:
                self._adb = self._adb_factory()
            phones = discover(self._adb)
        except (AdbError, OSError) as exc:
            self._say_once("adb", f"อ่านโทรศัพท์ผ่าน ADB ไม่ได้: {exc}")
            return []
        if not phones:
            self._say_once("none", "ไม่พบโทรศัพท์ — เสียบสาย USB และเปิด USB debugging")
            return []
        self._last.pop("none", None)
        try:
            results = register_ready(client, session, phones)
        except ServerError as exc:
            self._say_once("server", f"ส่งข้อมูลโทรศัพท์ไปที่เซิร์ฟเวอร์ไม่ได้: {exc.message}")
            return []
        for r in results:
            key = r.get("serial") or r.get("adb_serial")
            # Newly registered and already registered are the same state for announcements: the
            # reminder about missing details is shown once per run, not again a minute later.
            outcome = "BOUND" if r["outcome"] in ("REGISTERED", "ALREADY_REGISTERED") else r["outcome"]
            signature = f"{outcome}|{r['state']}|{','.join(r.get('missing_details') or [])}|{r.get('thai_keyboard')}"
            if self._last.get(key) != signature:
                self._last[key] = signature
                self._log(describe(r))
        return results

    def _say_once(self, key: str, message: str) -> None:
        if self._last.get(key) != message:
            self._last[key] = message
            self._log(message)
