"""The Thai keyboard on the phone: punpun Thai input (Q-44), earlier ADBKeyboard (Q-13).

A live post types the caption through this keyboard: Android's `input text` cannot type Thai or emoji.
The Agent does not carry the app (PO 2026-10-11): `install` downloads it from the punpun-agent release
page, accepts it only if its SHA-256 is the one built and checked here, installs it with adb and makes
it available (`ime enable`), never the phone's keyboard: the post runner switches to it while typing and
gives the owner's keyboard back every time (tiktok_ui.type_caption).

punpun Thai input is a GPL-2.0 fork of ADBKeyBoard (keyboard/, tools/build_keyboard.py): ADBKeyBoard
itself is now blocked by Google Play Protect as built for an older Android (QA phone, 2026-10-11). A phone
that still has ADBKeyBoard keeps working with it.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import urllib.request
from pathlib import Path

from agent.adb import Adb, AdbError

PACKAGE = "app.punpun.keyboard"
IME = f"{PACKAGE}/.PunpunIME"
LEGACY = {"com.android.adbkeyboard": "com.android.adbkeyboard/.AdbIME"}  # ADBKeyBoard (Q-13)
VERSION = "1.0"
APK_URL = f"https://github.com/piyasak/punpun-agent/releases/download/keyboard-v{VERSION}/punpun-keyboard-{VERSION}.apk"
APK_SHA256 = "c25a70775ce11018e0be8c6fcc476da4c706e1a97ec6be492f8f7cea845dbe33"
APK_MAX_BYTES = 1_000_000
SOURCE_URL = f"https://github.com/piyasak/punpun-agent/releases/tag/keyboard-v{VERSION}"  # source zip there


class KeyboardError(Exception):
    pass


def ime(adb: Adb, serial: str) -> str | None:
    """The keyboard to type with on this phone: ours, else ADBKeyBoard, else None."""
    packages = {line.strip().removeprefix("package:") for line in adb.shell(serial, "pm list packages").splitlines()}
    if PACKAGE in packages:
        return IME
    return next((ime_id for package, ime_id in LEGACY.items() if package in packages), None)


def installed(adb: Adb, serial: str) -> bool:
    return ime(adb, serial) is not None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(folder: Path, opener=urllib.request.urlopen) -> Path:
    """The checked APK in `folder` (downloaded once; a copy that does not match is replaced)."""
    path = folder / f"punpun-keyboard-{APK_SHA256[:12]}.apk"
    if path.is_file() and _sha256(path.read_bytes()) == APK_SHA256:
        return path
    try:
        with opener(APK_URL, timeout=60) as resp:
            data = resp.read(APK_MAX_BYTES + 1)
    except OSError as exc:
        raise KeyboardError(f"ดาวน์โหลดคีย์บอร์ดพิมพ์ไทยไม่ได้: {exc}") from None
    if len(data) > APK_MAX_BYTES or _sha256(data) != APK_SHA256:
        raise KeyboardError("ไฟล์คีย์บอร์ดที่ดาวน์โหลดมาไม่ตรงกับไฟล์ที่ตรวจไว้ จึงไม่ติดตั้ง")
    folder.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_bytes(data)
    part.replace(path)
    return path


def install(adb: Adb, serial: str, folder: Path, opener=urllib.request.urlopen) -> str:
    """Install on one phone if missing. Returns 'present' or 'installed'; raises KeyboardError."""
    if ime(adb, serial) == IME:
        adb.shell(serial, f"ime enable {IME}")
        return "present"
    apk = download(folder, opener)
    try:
        out = adb.install(serial, apk)
    except AdbError as exc:
        raise KeyboardError(install_hint(str(exc))) from None
    except subprocess.TimeoutExpired:
        # QA phone, 2026-10-11: Google Play Protect stopped the install with a dialog on the phone
        # ("built for an older version of Android") and adb waited until its timeout.
        out = "PLAY_PROTECT" if PLAY_PROTECT in adb.shell(serial, "dumpsys window | grep mCurrentFocus") else "TIMEOUT"
    if "Success" not in out or ime(adb, serial) != IME:
        raise KeyboardError(install_hint(out))
    adb.shell(serial, f"ime enable {IME}")  # available to switch to; the owner's keyboard stays the default
    return "installed"


PLAY_PROTECT = "com.android.vending/com.google.android.finsky.protectdialogs"


def install_hint(message: str) -> str:
    if message == "PLAY_PROTECT":
        return ("Google Play Protect บนโทรศัพท์หยุดการติดตั้งคีย์บอร์ดพิมพ์ไทยไว้ — "
                "ดูหน้าจอโทรศัพท์: การติดตั้งต่อหรือไม่เป็นการตัดสินใจของเจ้าของเครื่อง")
    if message == "TIMEOUT":
        return "โทรศัพท์ไม่ตอบระหว่างติดตั้ง — ดูหน้าจอโทรศัพท์ว่ามีหน้าต่างให้ยืนยันหรือไม่ แล้วกดติดตั้งอีกครั้ง"
    if "INSTALL_FAILED_VERIFICATION_FAILURE" in message or "INSTALL_FAILED_USER_RESTRICTED" in message:
        code = re.search(r"INSTALL_FAILED_\w+", message).group(0)
        # QA phone, 2026-10-11: refused once, installed on the next press (HyperOS asks on the phone).
        return ("โทรศัพท์ไม่ยอมให้ติดตั้งผ่าน USB: กดติดตั้งอีกครั้งแล้วดูหน้าจอโทรศัพท์ ถ้ามีหน้าต่างถามให้กด \"ติดตั้ง\"; "
                "Xiaomi/POCO/Redmi ต้องเปิด ตั้งค่า → ตัวเลือกสำหรับนักพัฒนา → \"ติดตั้งผ่าน USB\" (Install via USB) ไว้ก่อน"
                f" ({code})")
    return f"ติดตั้งคีย์บอร์ดพิมพ์ไทยไม่สำเร็จ: {message.strip()[:200]}"


def install_all(adb: Adb, folder: Path, opener=urllib.request.urlopen) -> list[str]:
    """Every ready phone on this PC: one Thai line each (settings window, `agent.cli thai-keyboard`)."""
    phones = [d for d in adb.devices() if d.ready]
    if not phones:
        return ["ไม่พบโทรศัพท์ที่พร้อม — เสียบสาย USB เปิด USB debugging แล้วกด \"อนุญาต\" บนโทรศัพท์"]
    lines = []
    for d in phones:
        name = d.model or d.serial
        try:
            done = install(adb, d.serial, folder, opener)
            lines.append(f"✓ {name}: {'มีคีย์บอร์ดพิมพ์ไทยอยู่แล้ว' if done == 'present' else 'ติดตั้งคีย์บอร์ดพิมพ์ไทยแล้ว'}")
        except (KeyboardError, AdbError) as exc:
            lines.append(f"✗ {name}: {exc}")
    return lines
