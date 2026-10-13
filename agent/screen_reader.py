"""A second way to read the phone screen, for screens that never stop moving (PO 2026-10-13).

`uiautomator dump` waits for the screen to be still and gives up with "could not get idle state" when
something keeps changing. tx1 (@jk.mickey, 2026-10-13): Profile opened on the TikTok Shop tab, whose
flash-sale countdown changes every second, so the account was never read (ACCOUNT_UNREADABLE).

openatx's uiautomator2 server (u2.jar, MIT) reads the same tree without waiting for a still screen. The
Agent does not carry it (as with the keyboard and FFmpeg): the first time a phone needs it, the jar is
downloaded at one fixed version and kept only if its SHA-256 is the one checked here. It runs on the phone
with app_process from /data/local/tmp (nothing installed, nothing for Play Protect to check) and is asked
over an adb port forward on 127.0.0.1 only. It only reads: presses and typing stay with the Agent.

Only TikTok's own window is read (root_in_active), as `uiautomator dump` does, so the status bar and
notifications never count as buttons. While it runs, `uiautomator dump` is killed, and it shows emoji as
".." (tx1, 2026-10-13), so TikTokUi stops it before every caption check (TikTokUi.read exact) and close().
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from agent import net
from agent.adb import Adb, AdbError

VERSION = "0.4.0"
JAR_URL = f"https://github.com/openatx/android-uiautomator-server-jar/releases/download/{VERSION}/u2.jar"
JAR_SHA256 = "0b74e83c55f443539a9f76f5ce023a51466b764b1100e4097a897053fdfc0eb6"  # checked 2026-10-13, 3,707,333 bytes
JAR_MAX_BYTES = 20_000_000
SOURCE_URL = "https://github.com/openatx/android-uiautomator-server"
REMOTE = "/data/local/tmp/punpun-u2.jar"
DEVICE_PORT = 9008
MAIN = "com.wetest.uia2.Main"
STOP = "pkill -f [c]om.wetest.uia2.Main"  # [c] keeps pkill from matching its own shell
MAX_DEPTH = 50

# Talks to 127.0.0.1 only: a system proxy must never see it.
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ReaderError(Exception):
    pass


def folder() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "ClipFlowAgent" / "uiautomator2"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(where: Path | None = None, opener=net.urlopen) -> Path:
    """The checked jar (downloaded once; a copy that does not match is replaced)."""
    where = where or folder()
    path = where / f"u2-{VERSION}.jar"
    if path.is_file() and _sha256(path.read_bytes()) == JAR_SHA256:
        return path
    try:
        with opener(JAR_URL, timeout=60) as resp:
            data = resp.read(JAR_MAX_BYTES + 1)
    except OSError as exc:
        raise ReaderError(f"could not download the screen reader: {exc}") from None
    if len(data) > JAR_MAX_BYTES or _sha256(data) != JAR_SHA256:
        raise ReaderError("the downloaded screen reader is not the checked file; not used")
    where.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_bytes(data)
    part.replace(path)
    return path


class U2Reader:
    def __init__(self, adb: Adb, serial: str, *, jar=download, http=_local.open, sleep=time.sleep,
                 start_timeout_s: float = 20.0):
        self.adb, self.serial, self.jar, self.http, self.sleep = adb, serial, jar, http, sleep
        self.start_timeout_s = start_timeout_s
        self.port: int | None = None

    def _ping(self) -> bool:
        try:
            with self.http(f"http://127.0.0.1:{self.port}/ping", timeout=3) as resp:
                return resp.read() == b"pong"
        except (OSError, urllib.error.URLError):
            return False

    def start(self) -> None:
        if self.port is not None and self._ping():
            return
        local = self.jar()
        expected = _sha256(Path(local).read_bytes())
        on_phone = self.adb.shell(self.serial, f"sha256sum {REMOTE} 2>/dev/null; true").split()
        if not on_phone or on_phone[0].lower() != expected:
            self.adb.push(self.serial, Path(local), REMOTE)
            on_phone = self.adb.shell(self.serial, f"sha256sum {REMOTE}").split()
            if not on_phone or on_phone[0].lower() != expected:
                raise ReaderError("the screen reader on the phone is not the checked file")
        self.adb.shell(self.serial, f"{STOP}; true")  # one server per phone: a leftover one goes first
        self.adb.shell(self.serial, f"CLASSPATH={REMOTE} setsid nohup app_process / {MAIN} -p {DEVICE_PORT}"
                                    " >/dev/null 2>&1 </dev/null &")
        if self.port is None:
            self.port = self.adb.forward(self.serial, DEVICE_PORT)
        deadline = time.monotonic() + self.start_timeout_s
        while not self._ping():
            if time.monotonic() >= deadline:
                self.stop()
                raise ReaderError("the screen reader did not start on the phone")
            self.sleep(0.5)

    def dump(self, all_windows: bool = False) -> str:
        """The XML of the window in front, in `uiautomator dump`'s format. `all_windows` adds the others
        (status bar, TikTok's floating banners): only for TikTokUi.dismiss_resume_banner."""
        self.start()
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "dumpWindowHierarchy",
                           "params": [False, MAX_DEPTH, not all_windows]}).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/jsonrpc/0", body,
                                         {"Content-Type": "application/json", "Accept-Encoding": ""})
        try:
            with self.http(request, timeout=30) as resp:
                answer = json.loads(resp.read())
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise ReaderError(f"the screen reader did not answer: {exc}") from None
        if not isinstance(answer, dict) or not isinstance(answer.get("result"), str):
            raise ReaderError(f"the screen reader could not read the screen: {str(answer)[:200]}")
        return answer["result"]

    def stop(self) -> None:
        try:
            self.adb.shell(self.serial, f"{STOP}; true")
            if self.port is not None:
                self.adb.forward_remove(self.serial, self.port)
        except AdbError:
            pass  # the phone went away; nothing is left running on this PC
        self.port = None
