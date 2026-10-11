"""ADB adapter for the Windows Agent (FR-15, FR-17).

Read-only device checks plus file transfer and Gallery (MediaStore) discovery.
It never taps the TikTok UI; posting is a separate, explicitly authorized step.
A runner is injected so parsing and decisions can be unit-tested without a phone;
those tests are logic checks, not evidence of device compatibility.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# TikTok ships under different package names per region (global / Asia builds).
TIKTOK_PACKAGES = ("com.zhiliaoapp.musically", "com.ss.android.ugc.trill")
REMOTE_DIR = "/sdcard/Movies/ClipFlow"
STAGING_DIR = ".incoming"  # hidden + .nomedia: never indexed by MediaStore

Runner = Callable[[list[str]], str]


class AdbError(Exception):
    pass


@dataclass(frozen=True)
class DeviceEntry:
    serial: str
    state: str  # device | unauthorized | offline | ...
    model: str | None = None

    @property
    def ready(self) -> bool:
        return self.state == "device"


def normalize_serial(serial: str) -> str:
    """Serials compare case-insensitively and without surrounding whitespace (architecture §2.4)."""
    return serial.strip().lower()


_VALIDATED_CAP = re.compile(r"Capabilities: \S*(?<![A-Z_])VALIDATED")


def wifi_online_from_dumpsys(dump: str) -> bool:
    """True when the "Current Networks:" block lists a Wi-Fi network with the VALIDATED capability.

    Only that block counts. "Transports: WIFI" and "VALIDATED" also appear in the
    Network Requests and Network Offers sections while Wi-Fi is off. Matching the
    whole dump reported "online" on a phone with Wi-Fi disabled (QA phone, 2026-10-07).
    """
    in_current = False
    for line in dump.splitlines():
        if line.startswith("Current Networks:"):
            in_current = True
            continue
        if in_current and line and not line[0].isspace():
            break  # next top-level section
        if in_current and "NetworkAgentInfo{" in line and "Transports: WIFI" in line and _VALIDATED_CAP.search(line):
            return True
    return False


def is_wireless_serial(serial: str) -> bool:
    """ADB over Wi-Fi (ip:port or mDNS tls-connect); turning Wi-Fi off would cut the Agent off."""
    return ":" in serial or "_adb-tls-connect" in serial


def parse_devices(output: str) -> list[DeviceEntry]:
    devices = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(("List of devices", "*")):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        model = next((p.split(":", 1)[1] for p in parts[2:] if p.startswith("model:")), None)
        devices.append(DeviceEntry(parts[0], parts[1], model))
    return devices


# adb could not reach its background server (the "daemon"), so the command never reached a phone and
# is safe to repeat. Seen on the QA PC, 2026-10-10: two Agent threads started the daemon at the same
# moment and one got "could not read ok from ADB Server / failed to start daemon".
DAEMON_DOWN = ("daemon not running", "cannot connect to daemon", "could not read ok from adb server",
               "failed to start daemon", "failed to check server version")
_server_lock = threading.Lock()


def daemon_down(message: str) -> bool:
    low = message.lower()
    return any(m in low for m in DAEMON_DOWN)


def bundled_adb() -> Path | None:
    """The adb shipped inside the packaged Agent (tools/build_agent.py), next to punpun-agent.exe."""
    from agent import packaged

    if not packaged():
        return None
    exe = Path(sys.executable).with_name("adb") / "adb.exe"
    return exe if exe.is_file() else None


def find_adb() -> str | None:
    """CLIPFLOW_ADB, then the Agent's own adb, then PATH: the customer needs no Android SDK."""
    env = os.environ.get("CLIPFLOW_ADB")
    if env and Path(env).is_file():
        return env
    own = bundled_adb()
    return str(own) if own else shutil.which("adb")


def start_server(exe: str, call=subprocess.run) -> None:
    """Start the adb daemon once at a time: concurrent starts are what fail."""
    with _server_lock, contextlib.suppress(OSError, subprocess.TimeoutExpired):
        call([exe, "start-server"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)


def default_runner(adb_path: str | None = None, *, retries: int = 3, wait_s: float = 1.0,
                   call=subprocess.run, sleep=time.sleep) -> Runner:
    exe = adb_path or find_adb()
    if not exe:
        raise AdbError("adb not found (the Agent's own adb is missing and none is on PATH)")

    def run(args: list[str]) -> str:
        empty_waits = [wait_s, 2 * wait_s, 2 * wait_s]
        attempt = 0
        while True:
            result = call([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            if result.returncode == 0:
                if args[:1] == ["devices"] and not parse_devices(result.stdout) and empty_waits:
                    # A daemon that has just started lists no phone until USB enumeration is done
                    # (packaged race test, 2026-10-10: 1 of 6 still empty after 1 s). Ask again for ~5 s.
                    sleep(empty_waits.pop(0))
                    continue
                return result.stdout
            message = (result.stderr or result.stdout).strip()
            attempt += 1
            if attempt <= retries and daemon_down(message):
                start_server(exe, call)  # under the lock; then the command again
                sleep(wait_s * attempt)
                continue
            raise AdbError(message)

    return run


def _ps(script: str) -> str:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip()


def adb_version(exe: str | None) -> str | None:
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"^Version (\S+)", out, re.M)
    return m.group(1) if m else None


def same_file(a: str | None, b: str | None) -> bool:
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def adb_report() -> dict:
    """Which adb the Agent uses, and which program holds the adb port (5037). Another adb of a different
    version (phone PC suites, scrcpy, Android Studio) restarts the daemon each time either one runs."""
    exe = find_adb()
    report = {"path": exe, "version": adb_version(exe), "bundled": bool(exe) and same_file(exe, str(bundled_adb())),
              "port_5037": None, "problems": []}
    if not exe:
        report["problems"].append("ไม่พบ adb: ติดตั้ง Agent ใหม่ด้วยไฟล์ setup (มี adb มาให้)")
        return report
    if sys.platform != "win32":
        return report
    owner = _ps("$c=Get-NetTCPConnection -LocalPort 5037 -State Listen -ErrorAction SilentlyContinue|Select-Object -First 1;"
                "if($c){$p=Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue;\"$($c.OwningProcess)|$($p.Path)\"}")
    if owner:
        pid, _, path = owner.partition("|")
        other_version = None if same_file(path, exe) else adb_version(path or None)
        report["port_5037"] = {"pid": int(pid) if pid.isdigit() else None, "path": path or None,
                               "version": report["version"] if same_file(path, exe) else other_version}
        if path and not same_file(path, exe) and other_version != report["version"]:
            report["problems"].append(
                f"พอร์ต ADB (5037) ถูกใช้โดย {path} เวอร์ชัน {other_version or 'ไม่ทราบ'} ซึ่งต่างจากของ Agent "
                f"({report['version']}): ปิดโปรแกรมนั้น (เช่น Mi PC Suite, scrcpy, Android Studio) แล้วเริ่ม Agent ใหม่")
    return report


@dataclass
class DoctorReport:
    serial: str
    state: str
    model: str | None = None
    android_release: str | None = None
    sdk: int | None = None
    tiktok_package: str | None = None
    tiktok_version: str | None = None
    screen_on: bool | None = None
    has_sha256sum: bool | None = None
    problems: list[str] | None = None

    @property
    def ready(self) -> bool:
        return not self.problems


class Adb:
    def __init__(self, runner: Runner):
        self._run = runner

    def devices(self) -> list[DeviceEntry]:
        return parse_devices(self._run(["devices", "-l"]))

    def shell(self, serial: str, command: str) -> str:
        return self._run(["-s", serial, "shell", command])

    def doctor(self, serial: str) -> DoctorReport:
        match = [d for d in self.devices() if normalize_serial(d.serial) == normalize_serial(serial)]
        if not match:
            return DoctorReport(serial, "not_connected", problems=["device not connected"])
        entry = match[0]
        report = DoctorReport(entry.serial, entry.state, entry.model, problems=[])
        if not entry.ready:
            report.problems.append(
                "authorize USB debugging on the phone" if entry.state == "unauthorized" else f"device state is {entry.state}"
            )
            return report
        report.model = self.shell(entry.serial, "getprop ro.product.model").strip() or entry.model
        report.android_release = self.shell(entry.serial, "getprop ro.build.version.release").strip()
        sdk = self.shell(entry.serial, "getprop ro.build.version.sdk").strip()
        report.sdk = int(sdk) if sdk.isdigit() else None
        packages = self.shell(entry.serial, "pm list packages").split()
        installed = {p.removeprefix("package:") for p in packages}
        report.tiktok_package = next((p for p in TIKTOK_PACKAGES if p in installed), None)
        if report.tiktok_package:
            dump = self.shell(entry.serial, f"dumpsys package {report.tiktok_package} | grep versionName")
            report.tiktok_version = dump.strip().split("=", 1)[-1] or None
        else:
            report.problems.append("TikTok app not installed")
        power = self.shell(entry.serial, "dumpsys power | grep -E 'mWakefulness=|Display Power'")
        report.screen_on = "Awake" in power or "state=ON" in power
        report.has_sha256sum = "sha256sum" in self.shell(entry.serial, "command -v sha256sum || echo missing")
        if not report.has_sha256sum:
            report.problems.append("sha256sum not available; cannot verify transfers")
        return report

    def push_verified(self, serial: str, local: Path, remote_dir: str = REMOTE_DIR, remote_name: str | None = None) -> str:
        """Push to a hidden staging name, verify SHA-256 on the device, then rename into place.

        P1 real-device fault test: killing the Agent mid-push left `adb push` running
        as an orphan, which finished writing an unverified file under the final name
        in a Gallery-indexed folder. Staging under `.incoming/` (with `.nomedia`, and a
        unique name per push) means the Gallery and TikTok only ever see verified files;
        the rename is atomic on the same filesystem.
        """
        expected = hashlib.sha256(local.read_bytes()).hexdigest()
        staging_dir = f"{remote_dir}/{STAGING_DIR}"
        staging = f"{staging_dir}/{uuid.uuid4().hex}.part"
        remote = f"{remote_dir}/{remote_name or local.name}"
        self.shell(serial, f"mkdir -p '{staging_dir}' && touch '{staging_dir}/.nomedia'")
        self._run(["-s", serial, "push", str(local), staging])
        output = self.shell(serial, f"sha256sum '{staging}'").split()
        actual = output[0] if output else ""
        if actual.lower() != expected:
            self.shell(serial, f"rm -f '{staging}'")
            raise AdbError(f"hash mismatch after push: expected {expected}, device has {actual}")
        self.shell(serial, f"mv -f '{staging}' '{remote}'")
        return remote

    # --- Wi-Fi and app control (power saving, Q-23) ---------------------------------

    def wifi_state(self, serial: str) -> tuple[bool, bool]:
        """(enabled, online): online = a *current* Wi-Fi network Android has VALIDATED for internet.

        Only booleans are returned; SSID, BSSID and IP are never logged.
        """
        enabled = self.shell(serial, "settings get global wifi_on").strip() not in ("", "0")
        online = enabled and wifi_online_from_dumpsys(self.shell(serial, "dumpsys connectivity"))
        return enabled, online

    def set_wifi(self, serial: str, enabled: bool) -> None:
        state = "enabled" if enabled else "disabled"
        out = self.shell(serial, f"cmd wifi set-wifi-enabled {state} 2>&1")
        if "Exception" in out or "Unknown command" in out:
            self.shell(serial, f"svc wifi {'enable' if enabled else 'disable'}")

    def wait_wifi_online(self, serial: str, timeout_s: float = 45.0, poll_s: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout_s
        while True:
            if self.wifi_state(serial)[1]:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll_s)

    def force_stop(self, serial: str, package: str) -> None:
        self.shell(serial, f"am force-stop {package}")

    def clean_staging(self, serial: str, remote_dir: str = REMOTE_DIR) -> None:
        """Remove leftovers of interrupted pushes (run on Agent start, before any new push)."""
        self.shell(serial, f"rm -f '{remote_dir}/{STAGING_DIR}/'*.part")

    def scan_and_find(self, serial: str, remote: str, timeout_s: float = 20.0) -> bool:
        """Ask the media scanner to index the file, then wait until MediaStore lists it."""
        self.shell(serial, f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d 'file://{remote}'")
        name = remote.rsplit("/", 1)[-1]
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            rows = self.shell(
                serial,
                f"content query --uri content://media/external/video/media --projection _display_name --where \"_display_name='{name}'\"",
            )
            if name in rows:
                return True
            time.sleep(1)
        return False
