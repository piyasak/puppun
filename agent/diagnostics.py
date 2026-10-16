"""Phone screen diagnostics (PO 2026-10-16): what the phone shows, sent to the web.

Nobody can reach this PC from outside, so when TikTok shows something unexpected the Agent sends it:
- `capture_failure`: a post stopped on a TikTok screen: the screen at that moment (PNG screenshot and the
  screen reading as XML), tied to the post;
- `run_requested`: a person asked for a check of a phone on the web: read-only steps (CHECKS), one capture
  after each. The steps press only tabs and grid tiles through TikTokUi (whose never-press rules still
  apply), pause a video with a tap, and never type, post or change anything; TikTok is closed afterwards.

Diagnostics never stop posting: every failure here is swallowed and logged. The server keeps captures
for 7 days and shows them only to the Workspace and platform staff (services/api/clipflow_api/diagnostics.py).
"""

from __future__ import annotations

import contextlib
import tempfile
import uuid
from pathlib import Path

from agent.tiktok_ui import TikTokUi, UiStop

REMOTE_SHOT = "/sdcard/cf_diag.png"
CHECKS = ("profile", "newest_public_video", "newest_private_video")


def capture(ui: TikTokUi, read_first: bool = True) -> list[tuple[str, bytes]]:
    """[("png", screenshot), ("xml", screen reading)] of the screen now; what cannot be taken is left out."""
    files: list[tuple[str, bytes]] = []
    try:
        ui.sh(f"screencap -p {REMOTE_SHOT}")
        with tempfile.TemporaryDirectory(prefix="cf-diag-") as tmp:
            local = Path(tmp) / "shot.png"
            ui.adb.pull(ui.serial, REMOTE_SHOT, local)
            data = local.read_bytes()
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                files.append(("png", data))
    except Exception:  # noqa: BLE001 - a missing screenshot must not stop the rest
        pass
    finally:
        with contextlib.suppress(Exception):
            ui.sh(f"rm -f {REMOTE_SHOT}")
    try:
        if read_first:
            ui.read(check=False)
        if ui.last_xml:
            files.append(("xml", ui.last_xml.encode("utf-8")))
    except Exception:  # noqa: BLE001
        pass
    return files


def upload(client, session, diag_id: str, step: int, name: str, files: list[tuple[str, bytes]]) -> None:
    for ext, data in files:
        client.diagnostic_file(session, diag_id, step, name, ext, data)


def capture_failure(client, session, ui: TikTokUi, serial: str, post_id: str | None, code: str, log) -> None:
    """Best effort, never raises: the screen when a post stopped on `code`."""
    try:
        files = capture(ui, read_first=False) or capture(ui)
        if not files:
            return
        diag_id = client.diagnostic_failure(session, serial, post_id, code)
        upload(client, session, diag_id, 0, "stopped", files)
        client.diagnostic_done(session, diag_id, note=code)
        log(f"ตรวจหน้าจอ: ส่งภาพหน้าจอตอนหยุด ({code}) ไปที่เว็บแล้ว")
    except Exception as exc:  # noqa: BLE001 - diagnostics must never change what happens to the post
        log(f"ตรวจหน้าจอ: ส่งภาพตอนหยุดไม่ได้ ({type(exc).__name__})")


def _first_tile(ui: TikTokUi, below_label: tuple[str, ...]) -> tuple[int, int] | None:
    nodes = ui.read()
    row = ui.find(nodes, *below_label)
    if row is None:
        return None
    tiles = sorted((n for n in nodes if n.rid.endswith(ui.p.grid_tile_id) and n.clickable and n.bounds[1] >= row.bounds[3]),
                   key=lambda n: (n.bounds[1], n.bounds[0]))
    return tiles[0].center if tiles else None


def run_check(ui: TikTokUi, check: str, snap) -> None:
    """The read-only steps of one check; `snap(name)` uploads the screen after each step."""
    if check not in CHECKS:
        raise UiStop("UNKNOWN_CHECK", check)
    ui.account(require=False)
    snap("profile")
    if check == "profile":
        return
    if check == "newest_public_video":
        ui.open_videos_tab()
        ui.sleep(ui.settle_s)
        snap("videos_tab")
        point = _first_tile(ui, ui.p.labels("private_tab"))
    else:
        ui.press(*ui.p.labels("private_tab"))
        ui.sleep(ui.settle_s * 2)
        snap("private_tab")
        locks = sorted((n for n in ui.read() if n.desc in ui.p.labels("lock_desc") and n.bounds[1] > 850),
                       key=lambda n: (n.bounds[1], n.bounds[0]))
        point = (locks[0].center[0], locks[0].center[1] - 60) if locks else None
    if point is None:
        raise UiStop("NO_VIDEO", "no video tile on Profile")
    x, y = point
    ui.sh(f"input swipe {x} {y} {x} {y} 120")  # the newest tile: opens the video, nothing else
    ui.sleep(ui.settle_s * 2)
    ui.sh("input tap 360 650")  # pause, so the screen can be read
    ui.sleep(ui.settle_s)
    snap("newest_video")


def run_requested(client, session, adb, serial: str, request: dict, profile, log, ui_factory=None) -> None:
    """One check asked for on the web; the result (or what stopped it) goes back to the server."""
    diag_id = request["id"]
    ui = (ui_factory or (lambda a, s: TikTokUi.for_phone(a, s, profile)))(adb, serial)
    step = [0]

    def snap(name: str) -> None:
        upload(client, session, diag_id, step[0], name, capture(ui))
        step[0] += 1

    error = None
    try:
        run_check(ui, request["check"], snap)
    except UiStop as exc:
        error = f"{exc.code}: {exc.detail}"[:300]
        with contextlib.suppress(Exception):
            snap("stopped")
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        with contextlib.suppress(Exception):
            ui.close()
    client.diagnostic_done(session, diag_id, note=f"{step[0]} screens", error=error)
    log(f"ตรวจหน้าจอ {request['check']} ({str(uuid.UUID(diag_id))[:8]}): " + ("เสร็จ" if not error else f"หยุด ({error})"))
