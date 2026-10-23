"""Clean start (PO 2026-10-23): the apps open on the phones are closed before the Agent takes work."""

from __future__ import annotations

from agent import clean_start
from agent.adb import AdbError, DeviceEntry


class FakeAdb:
    def __init__(self, entries, broken=()):
        self.entries, self.broken, self.calls = entries, set(broken), []

    def devices(self):
        return self.entries

    def shell(self, serial, command):
        if serial in self.broken:
            raise AdbError("device offline")
        self.calls.append((serial, command))
        if command == "pm list packages -3":
            return ("package:com.ss.android.ugc.trill\npackage:app.punpun.keyboard\npackage:com.facebook.katana\n"
                    "package:com.other.ime\npackage:com.mi.android.globallauncher\n")
        if command.startswith("settings get secure default_input_method"):
            return "com.other.ime/.Service\n"
        if command.startswith("cmd package resolve-activity"):
            return "priority=0 preferredOrder=0\ncom.mi.android.globallauncher/com.miui.home.Launcher\n"
        return ""


def test_every_ready_phone_goes_home_and_its_apps_are_closed_except_keyboards_and_home():
    adb = FakeAdb([DeviceEntry("A", "device"), DeviceEntry("B", "unauthorized")])
    logs = []
    assert clean_start.clean_all(adb, logs.append) == {"A": 2}
    commands = [c for s, c in adb.calls if s == "A"]
    assert commands[0] == "input keyevent KEYCODE_HOME"
    stop = next(c for c in commands if c.startswith("am force-stop"))
    assert stop == "am force-stop com.facebook.katana; am force-stop com.ss.android.ugc.trill"
    for kept in ("app.punpun.keyboard", "com.other.ime", "globallauncher"):
        assert kept not in stop
    assert commands[-1] == "am kill-all" and not any(s == "B" for s, _ in adb.calls)  # not ready: untouched
    assert "2 แอป" in logs[0]


def test_a_phone_that_fails_is_skipped_and_the_agent_starts_anyway():
    adb = FakeAdb([DeviceEntry("A", "device"), DeviceEntry("B", "device")], broken={"A"})
    logs = []
    assert clean_start.clean_all(adb, logs.append) == {"B": 2}
    assert "ไม่ได้" in logs[0]

    class NoAdb(FakeAdb):
        def devices(self):
            raise AdbError("adb not running")

    assert clean_start.clean_all(NoAdb([]), logs.append) == {} and "ข้าม" in logs[-1]


def test_only_installed_apps_are_named_never_system_or_odd_names():
    adb = FakeAdb([DeviceEntry("A", "device")])
    adb.shell = lambda s, c: ("package:com.ok.app\npackage:bad;rm -rf /\n" if c == "pm list packages -3"
                              else "null\n" if "default_input_method" in c else "")
    calls = []
    original = adb.shell
    adb.shell = lambda s, c: calls.append(c) or original(s, c)
    assert clean_start.clean_phone(adb, "A") == ["com.ok.app"]
    assert not any("rm -rf" in c for c in calls)


def test_before_a_post_opens_tiktok_the_phone_is_cleaned_first(tmp_path):
    # PO 2026-10-23: close every app before each post, as on Agent start; a failure never stops the post.
    from agent.post_runner import PostRunner, _Post

    adb = FakeAdb([DeviceEntry("A", "device")])
    logs = []
    runner = PostRunner(tmp_path, adb_factory=lambda: adb, log=logs.append)

    class Phone:
        adb_serial, hw_serial = "A", "HWA"

    post = {"id": "f240f595-172b-40c3-bcc6-cda52feaf9d0", "attempt": 1, "state": "CLAIMED",
            "device": {"serial": "HWA"}, "text": {"caption": "x", "hashtags": []}}
    _Post(runner, None, None, post, adb, Phone())._clean_phone()
    commands = [c for _, c in adb.calls]
    assert commands[0] == "input keyevent KEYCODE_HOME" and "am force-stop com.ss.android.ugc.trill" in " ".join(commands)
    assert "2 แอป" in logs[-1]
    broken = FakeAdb([DeviceEntry("A", "device")], broken={"A"})
    _Post(runner, None, None, post, broken, Phone())._clean_phone()  # no exception
    assert "ไม่ได้" in logs[-1]
