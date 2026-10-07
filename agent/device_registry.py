"""Find phones over ADB and register the ready ones with the server (FR-15, P2.6).

The server identifies a phone by its hardware serial (`ro.serialno`), not by the ADB
transport id: an ADB-over-Wi-Fi id (`ip:port`) changes between connections. Phones that are
not ready (unauthorized/offline) are reported with a hint instead of being registered.
Read-only on the phone: only `getprop`.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.adb import Adb, is_wireless_serial


@dataclass(frozen=True)
class SeenPhone:
    adb_serial: str  # what `adb devices` shows (transport id)
    hw_serial: str | None  # ro.serialno; None when the phone cannot be queried
    state: str  # device | unauthorized | offline | ...
    model: str | None = None
    android_version: str | None = None


def discover(adb: Adb) -> list[SeenPhone]:
    phones = []
    for entry in adb.devices():
        if entry.ready:
            hw = adb.shell(entry.serial, "getprop ro.serialno").strip() or None
            model = adb.shell(entry.serial, "getprop ro.product.model").strip() or entry.model
            release = adb.shell(entry.serial, "getprop ro.build.version.release").strip() or None
            phones.append(SeenPhone(entry.serial, hw, entry.state, model, release))
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
            body = client.register_device(session, p.hw_serial, p.state, p.model, p.android_version)
            outcome = "REGISTERED" if body.get("created") else "ALREADY_REGISTERED"
            results.append({"serial": p.hw_serial, "state": p.state, "outcome": outcome, "device_id": body["id"]})
        except ServerError as exc:
            results.append({"serial": p.hw_serial, "state": p.state, "outcome": exc.code, "message": exc.message})
    client.report_devices(session, report_map(phones))
    return results
