"""ADB adapter for the Windows Agent (FR-15, FR-17).

Read-only device checks plus file transfer and Gallery (MediaStore) discovery.
It never taps the TikTok UI; posting is a separate, explicitly authorized step.
A runner is injected so parsing and decisions can be unit-tested without a phone;
those tests are logic checks, not evidence of device compatibility.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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


def default_runner(adb_path: str | None = None) -> Runner:
    exe = adb_path or shutil.which("adb")
    if not exe:
        raise AdbError("adb not found on PATH")

    def run(args: list[str]) -> str:
        result = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        if result.returncode != 0:
            raise AdbError((result.stderr or result.stdout).strip())
        return result.stdout

    return run


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

    def push_verified(self, serial: str, local: Path, remote_dir: str = REMOTE_DIR) -> str:
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
        remote = f"{remote_dir}/{local.name}"
        self.shell(serial, f"mkdir -p '{staging_dir}' && touch '{staging_dir}/.nomedia'")
        self._run(["-s", serial, "push", str(local), staging])
        output = self.shell(serial, f"sha256sum '{staging}'").split()
        actual = output[0] if output else ""
        if actual.lower() != expected:
            self.shell(serial, f"rm -f '{staging}'")
            raise AdbError(f"hash mismatch after push: expected {expected}, device has {actual}")
        self.shell(serial, f"mv -f '{staging}' '{remote}'")
        return remote

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
