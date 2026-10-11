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
        self.has_keyboard, self.install_out, self.calls, self.enabled = has_keyboard, install_out, [], False

    def __call__(self, args):
        self.calls.append(args)
        if args[:1] == ["devices"]:
            return "List of devices attached\nS1\tdevice product:x model:POCO_F7 device:x\n"
        if args[2:] == ["shell", "pm list packages"]:
            return "package:com.ss.android.ugc.trill\n" + ("package:app.punpun.keyboard\n" if self.has_keyboard else "")
        if args[2:] == ["shell", "ime enable app.punpun.keyboard/.PunpunIME"]:
            assert self.has_keyboard
            self.enabled = True
            return "Input method app.punpun.keyboard/.PunpunIME: now enabled\n"
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


def test_the_apk_comes_from_our_release_page_with_a_fixed_hash():
    assert thai_keyboard.APK_URL.startswith("https://github.com/piyasak/punpun-agent/releases/download/keyboard-v")
    assert len(APK_SHA256) == 64


def test_a_phone_with_only_adbkeyboard_still_types_with_it():
    def runner(args):
        return "package:com.android.adbkeyboard\n"

    assert thai_keyboard.ime(Adb(runner), "S1") == "com.android.adbkeyboard/.AdbIME"
    both = "package:com.android.adbkeyboard\npackage:app.punpun.keyboard\n"
    assert thai_keyboard.ime(Adb(lambda a: both), "S1") == thai_keyboard.IME  # ours first


def test_installs_once_only_where_missing_and_downloads_once(tmp_path):
    phone, get = Phone(), opener()
    adb = Adb(phone)
    assert thai_keyboard.install(adb, "S1", tmp_path, get) == "installed"
    assert thai_keyboard.install(adb, "S1", tmp_path, get) == "present"
    assert len(get.urls) == 1 and get.urls[0] == thai_keyboard.APK_URL
    assert sum(1 for c in phone.calls if "install" in c) == 1
    # Made available, never the phone's keyboard: `ime enable` only, no `ime set`.
    assert phone.enabled and not any("ime set" in " ".join(c) for c in phone.calls)


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
