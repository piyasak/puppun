"""The Thai keyboard on the phone (ADBKeyboard, Q-13/Q-44).

A live post types the caption through ADBKeyboard: Android's `input text` cannot type Thai or emoji.
The Agent does not carry the app (PO 2026-10-11): `install` downloads it from its author's repository
at one fixed commit, accepts it only if its SHA-256 is the one checked on the QA phone, and installs it
with adb. It is installed only, never made the phone's keyboard: the post runner switches to it while
typing and gives the owner's keyboard back every time (tiktok_ui.type_caption).
"""

from __future__ import annotations

import hashlib
import subprocess
import urllib.request
from pathlib import Path

from agent.adb import Adb, AdbError

PACKAGE = "com.android.adbkeyboard"
# senzhk/ADBKeyBoard (GPL-2.0), the APK at commit 8dd0b69 (2023-11-23) = master on 2026-10-11 = the copy
# on the QA phone since 2026-10-07 (17,374 bytes).
APK_URL = "https://raw.githubusercontent.com/senzhk/ADBKeyBoard/8dd0b6924e45ac5565f77f13cf8e8eaf47dbb1b0/ADBKeyboard.apk"
APK_SHA256 = "e698adea5633135a067b038f9a0cf41baa4de09888713a81593fb2b9682cdc59"
APK_MAX_BYTES = 1_000_000
SOURCE_URL = "https://github.com/senzhk/ADBKeyBoard"


class KeyboardError(Exception):
    pass


def installed(adb: Adb, serial: str) -> bool:
    out = adb.shell(serial, "pm list packages")
    return any(line.strip() == f"package:{PACKAGE}" for line in out.splitlines())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(folder: Path, opener=urllib.request.urlopen) -> Path:
    """The checked APK in `folder` (downloaded once; a copy that does not match is replaced)."""
    path = folder / f"ADBKeyboard-{APK_SHA256[:12]}.apk"
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
    if installed(adb, serial):
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
    if "Success" not in out or not installed(adb, serial):
        raise KeyboardError(install_hint(out))
    return "installed"


PLAY_PROTECT = "com.android.vending/com.google.android.finsky.protectdialogs"


def install_hint(message: str) -> str:
    if message == "PLAY_PROTECT":
        return ("Google Play Protect บนโทรศัพท์บล็อกการติดตั้ง ADBKeyboard (แอปสร้างไว้สำหรับ Android รุ่นเก่า) — "
                "ดูหน้าจอโทรศัพท์: การติดตั้งต่อหรือไม่เป็นการตัดสินใจของเจ้าของเครื่อง")
    if message == "TIMEOUT":
        return "โทรศัพท์ไม่ตอบระหว่างติดตั้ง — ดูหน้าจอโทรศัพท์ว่ามีหน้าต่างให้ยืนยันหรือไม่ แล้วกดติดตั้งอีกครั้ง"
    if "INSTALL_FAILED_VERIFICATION_FAILURE" in message or "INSTALL_FAILED_USER_RESTRICTED" in message:
        return ("โทรศัพท์ไม่ยอมให้ติดตั้งผ่าน USB: Xiaomi/POCO/Redmi ให้เปิด ตั้งค่า → ตัวเลือกสำหรับนักพัฒนา → "
                "\"ติดตั้งผ่าน USB\" (Install via USB) แล้วกดติดตั้งอีกครั้ง; บางรุ่นต้องกด \"ติดตั้ง\" บนหน้าจอโทรศัพท์")
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
