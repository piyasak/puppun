"""Agent logic tests with an injected fake adb runner. These prove decision logic
(G1-04 recovery rules, hash checks, parsing) and are NOT device-compatibility evidence."""

import hashlib

import pytest

from agent.adb import Adb, AdbError, normalize_serial, parse_devices
from agent.attempt import AttemptJournal, State, TransitionError

DEVICES_OUT = """List of devices attached
R58M12ABCDE            device usb:1-1 product:a51 model:SM_A515F device:a51 transport_id:1
emulator-5554          unauthorized transport_id:2
0123456789             offline transport_id:3

"""


def test_parse_devices_states_and_model():
    devices = parse_devices(DEVICES_OUT)
    assert [(d.serial, d.state, d.ready) for d in devices] == [
        ("R58M12ABCDE", "device", True),
        ("emulator-5554", "unauthorized", False),
        ("0123456789", "offline", False),
    ]
    assert devices[0].model == "SM_A515F"
    assert normalize_serial(" r58m12abcde ") == normalize_serial("R58M12ABCDE")


class FakeAdb:
    def __init__(self, responses, device_hash=None):
        self.responses = responses
        self.device_hash = device_hash
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["devices", "-l"]:
            return DEVICES_OUT
        if args[2] == "push":
            return "1 file pushed"
        command = args[3]
        if command.startswith("sha256sum"):
            return f"{self.device_hash}  /sdcard/x\n"
        for prefix, out in self.responses.items():
            if command.startswith(prefix):
                return out
        return ""


DOCTOR_OK = {
    "getprop ro.product.model": "SM-A515F\n",
    "getprop ro.build.version.release": "13\n",
    "getprop ro.build.version.sdk": "33\n",
    "pm list packages": "package:com.android.chrome\npackage:com.ss.android.ugc.trill\n",
    "dumpsys package": "    versionName=36.1.4\n",
    "dumpsys power": "  mWakefulness=Awake\n",
    "command -v sha256sum": "/system/bin/sha256sum\n",
}


def test_doctor_ready_device():
    report = Adb(FakeAdb(DOCTOR_OK)).doctor("r58m12abcde")
    assert report.ready, report.problems
    assert (report.model, report.android_release, report.sdk) == ("SM-A515F", "13", 33)
    assert report.tiktok_package == "com.ss.android.ugc.trill" and report.tiktok_version == "36.1.4"


def test_doctor_reports_unauthorized_and_missing_tiktok():
    assert Adb(FakeAdb(DOCTOR_OK)).doctor("emulator-5554").problems == ["authorize USB debugging on the phone"]
    no_tiktok = dict(DOCTOR_OK, **{"pm list packages": "package:com.android.chrome\n"})
    assert "TikTok app not installed" in Adb(FakeAdb(no_tiktok)).doctor("R58M12ABCDE").problems
    assert Adb(FakeAdb(DOCTOR_OK)).doctor("missing").problems == ["device not connected"]


def test_push_verified_rejects_and_removes_mismatched_file(tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video-bytes")
    good = Adb(FakeAdb({}, device_hash=hashlib.sha256(b"video-bytes").hexdigest()))
    assert good.push_verified("S1", clip).endswith("/clip.mp4")

    fake = FakeAdb({}, device_hash="0" * 64)
    with pytest.raises(AdbError, match="hash mismatch"):
        Adb(fake).push_verified("S1", clip)
    assert any(c[3].startswith("rm -f") for c in fake.calls if len(c) > 3)


# --- attempt journal: fault injection at every step (G1-04, T17, T18) --------

@pytest.mark.parametrize("crash_after", [State.CLAIMED, State.TRANSFERRING, State.PREPARING])
def test_crash_before_submit_is_retryable(tmp_path, crash_after):
    journal = AttemptJournal(tmp_path / "a.jsonl")
    journal.begin("a1")
    for state in [State.TRANSFERRING, State.PREPARING]:
        if journal.current("a1") == crash_after:
            break
        journal.advance("a1", state)
    # Process dies here; a fresh journal instance simulates the restarted Agent.
    restarted = AttemptJournal(tmp_path / "a.jsonl")
    assert restarted.recover("a1") == State.RETRYABLE_FAILED
    assert restarted.may_retry("a1")


@pytest.mark.parametrize("crash_in", [State.SUBMITTING, State.VERIFYING])
def test_crash_at_or_after_submit_is_unknown_and_never_retried(tmp_path, crash_in):
    journal = AttemptJournal(tmp_path / "a.jsonl")
    journal.begin("a1")
    for state in [State.TRANSFERRING, State.PREPARING, State.SUBMITTING, State.VERIFYING]:
        journal.advance("a1", state)
        if state == crash_in:
            break
    restarted = AttemptJournal(tmp_path / "a.jsonl")
    assert restarted.recover("a1") == State.UNKNOWN
    assert not restarted.may_retry("a1")
    assert restarted.recover("a1") == State.UNKNOWN  # recovery is idempotent
    with pytest.raises(TransitionError):
        restarted.advance("a1", State.SUBMITTING)  # no path back to submit
    with pytest.raises(TransitionError):
        restarted.begin("a1")  # the same attempt cannot be restarted


def test_torn_last_line_after_crash_keeps_earlier_state(tmp_path):
    path = tmp_path / "a.jsonl"
    journal = AttemptJournal(path)
    journal.begin("a1")
    journal.advance("a1", State.TRANSFERRING)
    journal.advance("a1", State.PREPARING)
    journal.advance("a1", State.SUBMITTING)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"attempt_id": "a1", "state": "VERIF')  # power loss mid-write
    assert AttemptJournal(path).recover("a1") == State.UNKNOWN


def test_unknown_resolution_requires_evidence_and_actor(tmp_path):
    journal = AttemptJournal(tmp_path / "a.jsonl")
    journal.begin("a1")
    for state in [State.TRANSFERRING, State.PREPARING, State.SUBMITTING]:
        journal.advance("a1", state)
    journal.recover("a1")
    with pytest.raises(TransitionError):
        journal.resolve("a1", "confirmed_not_published", evidence="", actor="support")
    assert journal.resolve("a1", "still_unknown", "profile not loaded", "owner") == State.UNKNOWN
    assert journal.resolve("a1", "confirmed_not_published", "profile checked 10:05, no post", "owner") == State.RETRYABLE_FAILED
    assert journal.may_retry("a1")


def test_cancel_not_allowed_once_submitting(tmp_path):
    journal = AttemptJournal(tmp_path / "a.jsonl")
    journal.begin("a1")
    for state in [State.TRANSFERRING, State.PREPARING, State.SUBMITTING]:
        journal.advance("a1", state)
    with pytest.raises(TransitionError):
        journal.advance("a1", State.CANCELLED)
