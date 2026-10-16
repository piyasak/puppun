"""Account numbers for the daily summary (Q-52, PO 2026-10-16): read on TikTok's Profile, read-only.

When a phone is free, about every STATS_EVERY the Agent opens Profile (as a screen check does), reads the
followers / following / likes counts and the view counts of the newest videos on the grid, and sends them
to the server, which keeps the history for Telegram summaries. Nothing is typed or posted; TikTok is closed
afterwards. A number that cannot be read is sent as unknown, never guessed.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from pathlib import Path

from agent.tiktok_ui import Node, TikTokUi, UiStop

STATS_EVERY_S = 12 * 3600
MAX_TILES = 12
_UNITS = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "พัน": 1_000, "หมื่น": 10_000, "แสน": 100_000,
          "ล้าน": 1_000_000}
_COUNT = re.compile(r"^\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k|m|b|พัน|หมื่น|แสน|ล้าน)?\s*$", re.IGNORECASE)


def parse_count(text: str) -> int | None:
    """'1,237' -> 1237, '1.2K' -> 1200, '3.4ล้าน' -> 3400000; anything else -> None."""
    m = _COUNT.match(text or "")
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    return int(round(value * _UNITS.get(unit, 1)))


def _number_above(nodes: list[Node], label: Node) -> int | None:
    """The count TikTok shows right above a label (same column), e.g. '1,237' over 'ผู้ติดตาม'."""
    lx1, ly1, lx2, _ = label.bounds
    best = None
    for n in nodes:
        value = parse_count(n.text)
        if value is None or n is label:
            continue
        x1, y1, x2, y2 = n.bounds
        cx = (x1 + x2) // 2
        if lx1 - 20 <= cx <= lx2 + 20 and y2 <= ly1 + 8 and ly1 - y2 < 80 and (best is None or y2 > best[0]):
            best = (y2, value)
    return best[1] if best else None


def read_profile(ui: TikTokUi) -> dict:
    handle = ui.account(require=False) or None
    nodes = ui.read()
    out: dict = {"account": handle, "followers": None, "following": None, "likes": None, "video_views": []}
    followers = ui.find(nodes, *ui.p.labels("followers"))
    for key, labels in (("following", ui.p.labels("following")), ("followers", ui.p.labels("followers")),
                        ("likes", ui.p.labels("likes_label"))):
        label = ui.find(nodes, *labels)
        if label is None:
            continue
        if key == "likes" and followers is not None and abs(label.center[1] - followers.center[1]) > 30:
            continue  # "ถูกใจ" elsewhere on the screen, not the counts row
        out[key] = _number_above(nodes, label)
    try:
        ui.open_videos_tab()
        ui.sleep(ui.settle_s)
        grid = ui.read()
        row = ui.find(grid, *ui.p.labels("private_tab"))
        if row is not None:
            tiles = sorted((n for n in grid if n.rid.endswith(ui.p.grid_tile_id) and n.clickable
                            and n.bounds[1] >= row.bounds[3]), key=lambda n: (n.bounds[1], n.bounds[0]))
            for tile in tiles[:MAX_TILES]:
                inside = [parse_count(n.text) for n in grid if n.text and tile.bounds[0] <= n.bounds[0]
                          and n.bounds[2] <= tile.bounds[2] and tile.bounds[1] <= n.bounds[1] and n.bounds[3] <= tile.bounds[3]]
                inside = [v for v in inside if v is not None]
                if inside:
                    out["video_views"].append(inside[0])
    except UiStop:
        pass  # the counts above are still worth sending
    return out


class StatsClock:
    """When each phone was last read (kept on this PC, so a restart does not read again at once)."""

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def due(self, serial: str, now: float | None = None) -> bool:
        return (now or time.time()) - float(self._load().get(serial, 0)) >= STATS_EVERY_S

    def mark(self, serial: str, now: float | None = None) -> None:
        data = self._load()
        data[serial] = now or time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")


def read_and_send(client, session, ui: TikTokUi, hw_serial: str, log) -> bool:
    """Best effort: True when numbers were sent. TikTok is closed afterwards; never raises."""
    try:
        numbers = read_profile(ui)
        client.account_stats(session, hw_serial, numbers)
        log(f"ยอดบัญชี @{numbers['account'] or '?'}: ผู้ติดตาม {numbers['followers']} • ถูกใจ {numbers['likes']}"
            f" • วิดีโอ {len(numbers['video_views'])} คลิป")
        return True
    except Exception as exc:  # noqa: BLE001 - numbers must never stop posting
        log(f"ยอดบัญชี: อ่านไม่ได้ ({type(exc).__name__})")
        return False
    finally:
        with contextlib.suppress(Exception):
            ui.close()
