"""A clean start on every phone (PO 2026-10-23): close the apps that are open before the Agent takes work.

When the Agent starts, each ready phone goes to its home screen, every installed (non-system) app is
force-stopped and background processes are cleared, so the first post never meets TikTok left on an old
screen (a feed with the Promote offer, an unfinished edit). Kept running: the keyboard captions are typed
with (punpun Thai input) and whatever keyboard is in use, and the home screen app. System apps are left
alone, nothing is uninstalled or changed in settings. A phone that cannot be cleaned is skipped and the
Agent starts anyway.
"""

from __future__ import annotations

from agent import thai_keyboard
from agent.adb import Adb, AdbError

KEEP = {thai_keyboard.PACKAGE}


def _package(component: str) -> str | None:
    """'com.x.ime/.Service' -> 'com.x.ime' (None for 'null' or an empty answer)."""
    text = component.strip().splitlines()[-1].strip() if component.strip() else ""
    package = text.split("/", 1)[0].strip()
    return package if package and package != "null" and "." in package else None


def kept(adb: Adb, serial: str) -> set[str]:
    keep = set(KEEP)
    ime = _package(adb.shell(serial, "settings get secure default_input_method"))
    home = _package(adb.shell(serial, "cmd package resolve-activity --brief -a android.intent.action.MAIN "
                                      "-c android.intent.category.HOME"))
    return keep | {p for p in (ime, home) if p}


def clean_phone(adb: Adb, serial: str) -> list[str]:
    """Home screen, force-stop the installed apps (not the kept ones), clear background processes.
    Returns the packages that were stopped."""
    adb.shell(serial, "input keyevent KEYCODE_HOME")
    installed = sorted(line.strip().removeprefix("package:") for line in
                       adb.shell(serial, "pm list packages -3").splitlines() if line.strip().startswith("package:"))
    keep = kept(adb, serial)
    stop = [p for p in installed if p not in keep and p.replace(".", "").replace("_", "").isalnum()]
    if stop:
        adb.shell(serial, "; ".join(f"am force-stop {p}" for p in stop))
    adb.shell(serial, "am kill-all")
    return stop


def clean_all(adb: Adb, log=print) -> dict[str, int]:
    """Every ready phone; never raises. Returns {adb serial: apps stopped} for the phones that were cleaned."""
    done: dict[str, int] = {}
    try:
        entries = [e for e in adb.devices() if e.ready]
    except (AdbError, OSError) as exc:
        log(f"เริ่มงาน: อ่านรายชื่อโทรศัพท์ไม่ได้ ({exc}) — ข้ามการปิดแอป")
        return done
    for entry in entries:
        try:
            stopped = clean_phone(adb, entry.serial)
        except (AdbError, OSError) as exc:
            log(f"เริ่มงาน: ปิดแอปบน {entry.serial} ไม่ได้ ({exc}) — เริ่มงานต่อ")
            continue
        done[entry.serial] = len(stopped)
        log(f"เริ่มงาน: ปิดแอปที่เปิดอยู่บน {entry.serial} แล้ว ({len(stopped)} แอป) กลับหน้าหลัก")
    return done
