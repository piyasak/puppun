"""Thai keyboard on the phone (Q-44): checked download from one fixed commit, install only when missing."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from agent import thai_keyboard
from agent.adb import Adb, AdbError
from agent.thai_keyboard import APK_SHA256, KeyboardError

GOOD = b"apk"


@pytest.fixture(autouse=True)
def good_hash(monkeypatch):
    monkeypatch.setattr(thai_keyboard, "APK_SHA256", hashlib.sha256(GOOD).hexdigest())


class Phone:
    def __init__(self, has_keyboard=False, install_out="Performing Streamed Install\nSuccess\n"):
        self.has_keyboard, self.install_out, self.calls = has_keyboard, install_out, []

    def __call__(self, args):
        self.calls.append(args)
        if args[:1] == ["devices"]:
            return "List of devices attached\nS1\tdevice product:x model:POCO_F7 device:x\n"
        if args[2:] == ["shell", "pm list packages"]:
            return "package:com.ss.android.ugc.trill\n" + ("package:com.android.adbkeyboard\n" if self.has_keyboard else "")
        if args[2] == "install":
            assert args[3] == "-r" and Path(args[4]).read_bytes() == GOOD
            if "Success" in self.install_out:
                self.has_keyboard = True
            return self.install_out
        raise AssertionError(args)


def opener(data=GOOD, fail=False):
    urls = []

    def open_(url, timeout):
        urls.append(url)
        if fail:
            raise OSError("offline")
        return io.BytesIO(data)

    open_.urls = urls
    return open_


def test_the_pinned_apk_is_the_one_checked_on_the_qa_phone():
    assert "/8dd0b6924e45ac5565f77f13cf8e8eaf47dbb1b0/" in thai_keyboard.APK_URL
    assert APK_SHA256 == "e698adea5633135a067b038f9a0cf41baa4de09888713a81593fb2b9682cdc59"


def test_installs_once_only_where_missing_and_downloads_once(tmp_path):
    phone, get = Phone(), opener()
    adb = Adb(phone)
    assert thai_keyboard.install(adb, "S1", tmp_path, get) == "installed"
    assert thai_keyboard.install(adb, "S1", tmp_path, get) == "present"
    assert len(get.urls) == 1 and get.urls[0] == thai_keyboard.APK_URL
    assert sum(1 for c in phone.calls if "install" in c) == 1
    # Never made the phone's keyboard: no ime command at all.
    assert not any("ime" in " ".join(c) for c in phone.calls)


def test_a_different_file_is_never_installed(tmp_path):
    phone = Phone()
    with pytest.raises(KeyboardError):
        thai_keyboard.install(Adb(phone), "S1", tmp_path, opener(b"something else"))
    assert not any("install" in c for c in phone.calls) and not list(tmp_path.glob("*.apk"))
    with pytest.raises(KeyboardError):
        thai_keyboard.install(Adb(phone), "S1", tmp_path, opener(fail=True))


def test_xiaomi_refusal_says_to_turn_on_install_via_usb(tmp_path):
    phone = Phone(install_out="Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]\n")
    lines = thai_keyboard.install_all(Adb(phone), tmp_path, opener())
    assert len(lines) == 1 and lines[0].startswith("✗ POCO_F7") and "Install via USB" in lines[0]


def test_an_adb_error_on_install_is_reported(tmp_path):
    def runner(args):
        if args[2:3] == ["install"]:
            raise AdbError("INSTALL_FAILED_VERIFICATION_FAILURE")
        return Phone()(args)

    with pytest.raises(KeyboardError, match="Install via USB"):
        thai_keyboard.install(Adb(runner), "S1", tmp_path, opener())


def test_play_protect_holding_the_install_is_said_not_a_crash(tmp_path):
    import subprocess

    def runner(args):
        if args[2:3] == ["install"]:
            raise subprocess.TimeoutExpired(args, 120)
        if args[2:] == ["shell", "dumpsys window | grep mCurrentFocus"]:
            return "  mCurrentFocus=Window{1 u0 com.android.vending/com.google.android.finsky.protectdialogs.activity.PlayProtectDialogsActivity}\n"
        return Phone()(args)

    lines = thai_keyboard.install_all(Adb(runner), tmp_path, opener())
    assert lines[0].startswith("✗") and "Play Protect" in lines[0]
