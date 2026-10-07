"""Phone discovery and registration flow on the Agent (logic only; real phone: test_real_device_registration)."""

from agent.adb import Adb
from agent.device_registry import discover, register_ready, report_map
from agent.server_client import ServerError

DEVICES = (
    "List of devices attached\n"
    "TST8YD89GI8XCIE6       device product:dew_p_global model:25078PC3EG device:dew transport_id:1\n"
    "R58M123ABC             unauthorized usb:1-1 transport_id:2\n"
    "192.168.6.30:5555      offline transport_id:3\n"
)
PROPS = {"ro.serialno": "TST8YD89GI8XCIE6", "ro.product.model": "25078PC3EG", "ro.build.version.release": "15"}


def runner(args):
    if args[:2] == ["devices", "-l"]:
        return DEVICES
    if args[2] == "shell" and args[3].startswith("getprop "):
        assert args[1] == "TST8YD89GI8XCIE6"  # only the ready phone is queried
        return PROPS[args[3].split()[1]] + "\n"
    raise AssertionError(args)


def test_discover_uses_hardware_serials_and_skips_wifi_ids():
    phones = {p.adb_serial: p for p in discover(Adb(runner))}
    ready = phones["TST8YD89GI8XCIE6"]
    assert (ready.hw_serial, ready.state, ready.model, ready.android_version) == (
        "TST8YD89GI8XCIE6", "device", "25078PC3EG", "15")
    assert phones["R58M123ABC"].hw_serial == "R58M123ABC"  # USB transport id = hardware serial
    assert phones["192.168.6.30:5555"].hw_serial is None   # Wi-Fi id is not an identity
    assert report_map(list(phones.values())) == {"TST8YD89GI8XCIE6": "device", "R58M123ABC": "unauthorized"}


class FakeClient:
    def __init__(self):
        self.reported = None

    def register_device(self, session, serial, state, model, version):
        if state != "device":
            raise ServerError(409, "DEVICE_NOT_READY", "not ready", {"adb_state": state})
        return {"id": "dev-1", "created": True}

    def report_devices(self, session, states):
        self.reported = states


def test_register_ready_reports_outcome_per_phone():
    client = FakeClient()
    results = register_ready(client, object(), discover(Adb(runner)))
    outcomes = {r.get("serial") or r.get("adb_serial"): r["outcome"] for r in results}
    assert outcomes == {"TST8YD89GI8XCIE6": "REGISTERED", "R58M123ABC": "DEVICE_NOT_READY",
                        "192.168.6.30:5555": "SERIAL_UNAVAILABLE"}
    assert client.reported == {"TST8YD89GI8XCIE6": "device", "R58M123ABC": "unauthorized"}


def test_register_only_one_phone():
    results = register_ready(FakeClient(), object(), discover(Adb(runner)), only="tst8yd89gi8xcie6")
    assert [r["outcome"] for r in results] == ["REGISTERED"]
