"""Phone power saving around a publish attempt (PO request 2026-10-07, Q-23).

Before a job the phone's Wi-Fi is switched on and the Agent waits until Android
reports the Wi-Fi network as VALIDATED (internet reachable). After the job the
posting app is closed and Wi-Fi is switched off again, but only once the
attempt's outcome is settled. While an attempt is SUBMITTING, VERIFYING or
UNKNOWN the app may still be uploading in the background and the result still
has to be checked, so the phone is left online (PRD section H: an ambiguous
post must stay reconcilable). Wi-Fi is never switched off when ADB itself runs
over Wi-Fi, because that would disconnect the Agent from the phone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.adb import TIKTOK_PACKAGES, Adb, is_wireless_serial
from agent.attempt import State

RELEASE_STATES = {State.VERIFIED_SUCCESS, State.RETRYABLE_FAILED, State.NEEDS_ACTION, State.CANCELLED}
KEEP_ONLINE_STATES = {State.CLAIMED, State.TRANSFERRING, State.PREPARING, State.SUBMITTING, State.VERIFYING, State.UNKNOWN}


class DeviceNotOnline(Exception):
    """Wi-Fi did not come online in time: the attempt must stop before Submit (NEEDS_ACTION)."""


@dataclass
class PowerReport:
    actions: list[str] = field(default_factory=list)
    kept_online_reason: str | None = None


def release_decision(state: State | None, serial: str) -> tuple[bool, str | None]:
    """Whether it is safe to close the app and switch Wi-Fi off now, and if not, why."""
    if state in KEEP_ONLINE_STATES or state is None:
        return False, f"attempt is {state}; the result is not settled yet"
    if state not in RELEASE_STATES:
        return False, f"unexpected state {state}"
    if is_wireless_serial(serial):
        return False, "ADB is connected over Wi-Fi; switching Wi-Fi off would disconnect the Agent"
    return True, None


class PowerSaver:
    def __init__(self, adb: Adb, serial: str, packages: tuple[str, ...] = TIKTOK_PACKAGES, online_timeout_s: float = 45.0):
        self.adb = adb
        self.serial = serial
        self.packages = packages
        self.online_timeout_s = online_timeout_s

    def prepare(self) -> PowerReport:
        report = PowerReport()
        enabled, online = self.adb.wifi_state(self.serial)
        if not enabled:
            self.adb.set_wifi(self.serial, True)
            report.actions.append("wifi_on")
        if not online and not self.adb.wait_wifi_online(self.serial, self.online_timeout_s):
            raise DeviceNotOnline(f"Wi-Fi not online within {self.online_timeout_s:.0f}s")
        report.actions.append("wifi_online")
        return report

    def release(self, state: State | None) -> PowerReport:
        report = PowerReport()
        ok, reason = release_decision(state, self.serial)
        if not ok:
            report.kept_online_reason = reason
            return report
        for package in self.packages:
            self.adb.force_stop(self.serial, package)
        report.actions.append("app_closed")
        self.adb.set_wifi(self.serial, False)
        if self.adb.wifi_state(self.serial)[0]:
            report.kept_online_reason = "Wi-Fi did not switch off"
        else:
            report.actions.append("wifi_off")
        return report
