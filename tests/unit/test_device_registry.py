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
    if args[2:] == ["shell", "pm list packages"]:
        assert args[1] == "TST8YD89GI8XCIE6"
        return "package:com.ss.android.ugc.trill\npackage:com.android.adbkeyboard\n"
    raise AssertionError(args)


def test_discover_uses_hardware_serials_and_skips_wifi_ids():
    phones = {p.adb_serial: p for p in discover(Adb(runner))}
    ready = phones["TST8YD89GI8XCIE6"]
    assert (ready.hw_serial, ready.state, ready.model, ready.android_version, ready.thai_keyboard) == (
        "TST8YD89GI8XCIE6", "device", "25078PC3EG", "15", True)
    assert phones["R58M123ABC"].hw_serial == "R58M123ABC"  # USB transport id = hardware serial
    assert phones["192.168.6.30:5555"].hw_serial is None   # Wi-Fi id is not an identity
    assert report_map(list(phones.values())) == {"TST8YD89GI8XCIE6": "device", "R58M123ABC": "unauthorized"}


class FakeClient:
    def __init__(self):
        self.reported = None

    def register_device(self, session, serial, state, model, version, thai_keyboard=None):
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


class RecordingClient(FakeClient):
    """Server stand-in that remembers registrations like the real one."""

    def __init__(self):
        super().__init__()
        self.known = {}

    def register_device(self, session, serial, state, model, version, thai_keyboard=None):
        if state != "device":
            raise ServerError(409, "DEVICE_NOT_READY", "ยังไม่พร้อม", {"adb_state": state})
        created = serial not in self.known
        self.known.setdefault(serial, {"display_name": None, "expected_account": None})
        info = self.known[serial]
        missing = [k for k in ("display_name", "expected_account") if not info[k]]
        return {"id": "dev-1", "created": created, **info, "missing_details": missing,
                "details_url": "http://web.example/devices?edit=dev-1"}


def test_phone_check_on_start_registers_and_points_to_the_web():
    from agent.device_registry import DeviceSync

    logs, client = [], RecordingClient()
    sync = DeviceSync(lambda: Adb(runner), log=logs.append)
    sync(client, object())
    registered = [m for m in logs if "TST8YD89GI8XCIE6" in m]
    assert registered == ["ลงทะเบียนโทรศัพท์ 25078PC3EG (TST8YD89GI8XCIE6) แล้ว — กรุณาไปใส่รายละเอียด "
                          "(ชื่อเรียกเครื่อง, บัญชี TikTok) ที่ http://web.example/devices?edit=dev-1"]
    assert any("R58M123ABC" in m and "ยังไม่พร้อม" in m for m in logs)
    assert any("Wi-Fi" in m for m in logs)

    # Next periodic check: nothing changed -> nothing new is printed.
    before = len(logs)
    sync(client, object())
    assert len(logs) == before

    # Owner filled in the details -> one "ready" line.
    client.known["TST8YD89GI8XCIE6"] = {"display_name": "POCO หน้าร้าน", "expected_account": "shop1"}
    sync(client, object())
    assert logs[-1] == "โทรศัพท์ POCO หน้าร้าน (TST8YD89GI8XCIE6) พร้อมใช้งาน (บัญชี TikTok @shop1)"


def test_phone_check_without_phones_or_adb_says_so_once():
    from agent.adb import AdbError
    from agent.device_registry import DeviceSync

    logs = []
    empty = DeviceSync(lambda: Adb(lambda args: "List of devices attached\n"), log=logs.append)
    empty(FakeClient(), object())
    empty(FakeClient(), object())
    assert logs == ["ไม่พบโทรศัพท์ — เสียบสาย USB และเปิด USB debugging"]

    def no_adb():
        raise AdbError("adb not found on PATH")

    logs.clear()
    missing = DeviceSync(no_adb, log=logs.append)
    assert missing(FakeClient(), object()) == [] and missing(FakeClient(), object()) == []
    assert logs == ["อ่านโทรศัพท์ผ่าน ADB ไม่ได้: adb not found on PATH"]


def test_a_phone_without_the_thai_keyboard_is_announced():
    from agent.device_registry import describe

    line = describe({"outcome": "ALREADY_REGISTERED", "serial": "S", "model": "M", "thai_keyboard": False})
    assert "ยังไม่มีคีย์บอร์ดพิมพ์ไทย" in line and "ติดตั้งคีย์บอร์ดพิมพ์ไทย" in line
    assert "คีย์บอร์ด" not in describe({"outcome": "ALREADY_REGISTERED", "serial": "S", "model": "M",
                                         "thai_keyboard": True, "expected_account": "qa"})
    with_details = describe({"outcome": "REGISTERED", "serial": "S", "model": "M", "thai_keyboard": False,
                             "details_url": "http://web/devices"})
    assert "http://web/devices" in with_details and "ติดตั้งคีย์บอร์ดพิมพ์ไทย" in with_details  # both said
