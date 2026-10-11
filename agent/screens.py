"""Phone screens on the PC (PO 2026-10-10): one scrcpy window per phone, laid out in a grid in the
order of the phones' names on the web, either controllable or view-only.

- scrcpy (Genymobile, Apache-2.0) ships with the packaged Agent (tools/build_agent.py) and is told
  to use the Agent's own adb (ADB environment variable), so two adb versions never fight over port
  5037 (E-51). Without the bundled copy, CLIPFLOW_SCRCPY or scrcpy on PATH is used.
- While the Agent drives TikTok on a phone, that phone's window is reopened view-only and given
  back afterwards, so a click on the PC cannot collide with a post (`ScreenWall.locked`).
- Nothing on the phone is changed: no stay-awake, no screen-off, no audio forwarding.
"""

from __future__ import annotations

import contextlib
import math
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

PHONE_ASPECT = 9 / 19.5  # width / height of a typical portrait phone screen
TITLE_BAR = 32  # px Windows adds above each window
MARGIN = 8


@dataclass(frozen=True)
class Phone:
    serial: str
    title: str


@dataclass(frozen=True)
class Cell:
    x: int
    y: int
    width: int
    height: int


def find_scrcpy() -> str | None:
    env = os.environ.get("CLIPFLOW_SCRCPY")
    if env and Path(env).is_file():
        return env
    from agent import packaged

    if packaged():
        own = Path(sys.executable).with_name("scrcpy") / "scrcpy.exe"
        if own.is_file():
            return str(own)
    return shutil.which("scrcpy")


def _natural(text: str) -> list:
    """"เครื่อง 2" before "เครื่อง 10"."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]


def ordered(connected: list[tuple[str, str]], named: list[dict]) -> list[Phone]:
    """Connected phones (adb serial, hardware serial) in the order of their names on the web; phones
    without a name go last. The web knows a phone by its hardware serial (ro.serialno, Q-25)."""
    by_serial = {d["serial"].strip().lower(): d for d in named}
    phones = []
    for serial, hw_serial in connected:
        d = by_serial.get((hw_serial or serial).strip().lower())
        name = (d or {}).get("display_name") or (d or {}).get("model") or serial
        account = (d or {}).get("expected_account")
        phones.append((d is None or not d.get("display_name"), _natural(name), serial,
                       Phone(serial, f"{name} • @{account}" if account else name)))
    return [p for *_, p in sorted(phones, key=lambda t: t[:3])]


def layout(n: int, area: tuple[int, int, int, int], aspect: float = PHONE_ASPECT) -> list[Cell]:
    """n portrait windows in a grid filling `area` (x, y, width, height) as large as they fit, in
    reading order (left to right, then the next row)."""
    if n <= 0:
        return []
    ax, ay, aw, ah = area
    best = None
    for cols in range(1, n + 1):
        rows = math.ceil(n / cols)
        cell_w = (aw - MARGIN * (cols + 1)) / cols
        cell_h = (ah - MARGIN * (rows + 1)) / rows - TITLE_BAR
        h = min(cell_h, cell_w / aspect)
        if h > 0 and (best is None or h > best[0]):
            best = (h, cols)
    h, cols = best if best else (100.0, n)
    w = int(h * aspect)
    h = int(h)
    cells = []
    for i in range(n):
        r, c = divmod(i, cols)
        cells.append(Cell(ax + MARGIN + c * (w + MARGIN), ay + MARGIN + r * (h + TITLE_BAR + MARGIN) + TITLE_BAR, w, h))
    return cells


def work_area() -> tuple[int, int, int, int]:
    """The primary screen without the taskbar (Windows); a 1920x1040 guess elsewhere."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return 0, 0, 1920, 1040


class ScreenWall:
    """The windows of the phones on this PC. `control=False` shows them view-only."""

    def __init__(self, scrcpy: str, adb: str | None, control: bool = True, log=print, popen=subprocess.Popen,
                 area: tuple[int, int, int, int] | None = None):
        self.scrcpy, self.adb, self.control, self.log, self.popen = scrcpy, adb, control, log, popen
        self.area = area
        self.windows: dict[str, tuple[Phone, Cell, bool, object]] = {}  # serial -> (phone, cell, control, process)
        self.busy: set[str] = set()
        self._lock = threading.Lock()

    def _open(self, phone: Phone, cell: Cell, control: bool):
        args = [self.scrcpy, "-s", phone.serial, "--window-title", phone.title + ("" if control else " (ดูอย่างเดียว)"),
                f"--window-x={cell.x}", f"--window-y={cell.y}", f"--window-width={cell.width}",
                f"--window-height={cell.height}", "--no-audio", "--max-size=1024", "--max-fps=30", "--no-power-on"]
        if not control:
            args.append("--no-control")
        env = {**os.environ, **({"ADB": self.adb} if self.adb else {})}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return self.popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)

    @staticmethod
    def _close(process) -> None:
        with contextlib.suppress(Exception):
            process.terminate()

    def show(self, phones: list[Phone]) -> None:
        """Open, move or close windows so the given phones are shown in this order."""
        with self._lock:
            cells = layout(len(phones), self.area or work_area())
            wanted = {p.serial: (p, c) for p, c in zip(phones, cells, strict=True)}
            for serial, (phone, cell, _control, proc) in list(self.windows.items()):
                alive = getattr(proc, "poll", lambda: None)() is None
                if serial not in wanted or wanted[serial] != (phone, cell) or not alive:
                    self._close(proc)
                    del self.windows[serial]
            for serial, (phone, cell) in wanted.items():
                if serial not in self.windows:
                    control = self.control and serial not in self.busy
                    self.windows[serial] = (phone, cell, control, self._open(phone, cell, control))

    def _set_control(self, serial: str, control: bool) -> None:
        with self._lock:
            if serial not in self.windows:
                return
            phone, cell, now, proc = self.windows[serial]
            if now == control:
                return
            self._close(proc)
            self.windows[serial] = (phone, cell, control, self._open(phone, cell, control))

    @contextlib.contextmanager
    def locked(self, serial: str):
        """View-only while the Agent works on this phone; control comes back afterwards."""
        self.busy.add(serial)
        if self.control:
            self._set_control(serial, False)
        try:
            yield
        finally:
            self.busy.discard(serial)
            if self.control:
                self._set_control(serial, True)

    def close(self) -> None:
        with self._lock:
            for _phone, _cell, _control, proc in self.windows.values():
                self._close(proc)
            self.windows.clear()


class ScreenWorker:
    """Keeps the wall in step with the phones on this PC and their names on the web (every 30 s)."""

    def __init__(self, wall: ScreenWall, adb_factory, log=print, every_s: float = 30.0):
        self.wall, self.adb_factory, self.log, self.every_s = wall, adb_factory, log, every_s
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None

    def refresh(self, client, get_session) -> list[Phone]:
        from agent.device_registry import discover

        phones = [(p.adb_serial, p.hw_serial) for p in discover(self.adb_factory()) if p.state == "device"]
        try:
            named = client.devices(get_session())
        except Exception:  # noqa: BLE001 - names are nice to have; the windows still open in serial order
            named = []
        shown = ordered(phones, named)
        self.wall.show(shown)
        return shown

    def _loop(self, client, get_session) -> None:
        while not self._halt.is_set():
            try:
                self.refresh(client, get_session)
            except Exception as exc:  # noqa: BLE001 - never stop the Agent over a preview window
                self.log(f"หน้าจอโทรศัพท์: แสดงไม่ได้ชั่วคราว ({exc})")
            self._halt.wait(self.every_s)

    def start(self, client, get_session) -> None:
        self._thread = threading.Thread(target=self._loop, args=(client, get_session), daemon=True,
                                        name="clipflow-screens")
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout_s)
        self.wall.close()
