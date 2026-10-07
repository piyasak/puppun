"""Power saving (Q-23) with a fake phone. Logic only; the real-device run is in docs/compatibility.md."""

import pytest

from agent.adb import Adb, is_wireless_serial
from agent.attempt import State
from agent.power import DeviceNotOnline, PowerSaver, release_decision


# Trimmed from the QA phone's real `dumpsys connectivity` (2026-10-07). The Requests and
# Offers sections mention WIFI and VALIDATED even while Wi-Fi is off.
_NOISE = """Network Requests:
  uid/pid:1000/1613 activeRequest: null callbackRequest: 6 [NetworkRequest [ LISTEN id=6, [ Transports: WIFI Capabilities: NOT_RESTRICTED&TRUSTED&NOT_VPN&VALIDATED ] ] ]
Network Offers:
  NetworkOffer [ Provider Id (8) Score(Policies : EVER_EVALUATED&IS_UNMETERED&EVER_VALIDATED&IS_VALIDATED ; KeepConnected : 0) Caps [ Transports: WIFI Capabilities: INTERNET ] ]
"""
DUMP_OFF = "Active default network: none\n\nCurrent Networks:\n\nStatus for known UIDs:\n" + _NOISE
DUMP_ONLINE = (
    "Active default network: 268\n\nCurrent Networks:\n"
    "  NetworkAgentInfo{network{268}  ni{WIFI CONNECTED extra: } nc{[ Transports: WIFI Capabilities: "
    "NOT_METERED&INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&VALIDATED&NOT_ROAMING&FOREGROUND ]}\n"
    "Status for known UIDs:\n" + _NOISE
)
DUMP_CONNECTING = DUMP_ONLINE.replace("&VALIDATED&", "&")  # associated, internet not validated yet


def test_online_parser_ignores_requests_and_offers_sections():
    from agent.adb import wifi_online_from_dumpsys

    assert wifi_online_from_dumpsys(DUMP_ONLINE) is True
    assert wifi_online_from_dumpsys(DUMP_OFF) is False  # regression: was True on the real phone
    assert wifi_online_from_dumpsys(DUMP_CONNECTING) is False


class FakePhone:
    """Simulates `adb shell` for Wi-Fi and app control."""

    def __init__(self, wifi_on=True, comes_online=True):
        self.wifi_on = wifi_on
        self.comes_online = comes_online
        self.commands = []

    def __call__(self, args):
        cmd = args[3]
        self.commands.append(cmd)
        if cmd == "settings get global wifi_on":
            return "1\n" if self.wifi_on else "0\n"
        if cmd.startswith("dumpsys connectivity"):
            return DUMP_ONLINE if (self.wifi_on and self.comes_online) else DUMP_OFF
        if cmd.startswith("cmd wifi set-wifi-enabled"):
            self.wifi_on = "enabled" in cmd and "disabled" not in cmd
            return ""
        return ""


def saver(phone, serial="TST8YD89GI8XCIE6"):
    return PowerSaver(Adb(phone), serial, online_timeout_s=0.01)


def test_prepare_turns_wifi_on_and_waits_until_online():
    phone = FakePhone(wifi_on=False)
    report = saver(phone).prepare()
    assert report.actions == ["wifi_on", "wifi_online"]
    assert phone.wifi_on


def test_prepare_fails_when_wifi_never_validates():
    with pytest.raises(DeviceNotOnline):
        saver(FakePhone(wifi_on=False, comes_online=False)).prepare()


def test_release_after_verified_success_closes_app_and_wifi():
    phone = FakePhone()
    report = saver(phone).release(State.VERIFIED_SUCCESS)
    assert report.actions == ["app_closed", "wifi_off"] and report.kept_online_reason is None
    assert any(c == "am force-stop com.ss.android.ugc.trill" for c in phone.commands)
    assert not phone.wifi_on


@pytest.mark.parametrize("state", [State.SUBMITTING, State.VERIFYING, State.UNKNOWN, State.PREPARING, None])
def test_unsettled_attempt_keeps_phone_online(state):
    phone = FakePhone()
    report = saver(phone).release(state)
    assert report.actions == [] and "not settled" in report.kept_online_reason
    assert phone.wifi_on and not any("force-stop" in c for c in phone.commands)


@pytest.mark.parametrize("state", [State.RETRYABLE_FAILED, State.NEEDS_ACTION, State.CANCELLED])
def test_settled_non_success_states_also_release(state):
    assert release_decision(state, "TST8YD89GI8XCIE6") == (True, None)


@pytest.mark.parametrize("serial", ["192.168.6.30:5555", "adb-TST8YD89-abc._adb-tls-connect._tcp"])
def test_never_switch_wifi_off_when_adb_runs_over_wifi(serial):
    assert is_wireless_serial(serial)
    phone = FakePhone()
    report = saver(phone, serial).release(State.VERIFIED_SUCCESS)
    assert "over Wi-Fi" in report.kept_online_reason and phone.wifi_on
