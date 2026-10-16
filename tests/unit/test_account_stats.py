"""Account numbers read on Profile (Q-52): counts, the view grid, and how often (synthetic screens only)."""

from __future__ import annotations

from agent import account_stats
from agent.tiktok_ui import Node, TikTokUi, UiStop


def node(text, bounds, rid="", clickable=False):
    return Node(text=text, desc="", rid=rid, cls="android.widget.TextView", clickable=clickable, bounds=bounds)


PROFILE = [
    node("@shop.test", (300, 400, 780, 450)),
    node("405", (150, 500, 330, 560)), node("กำลังติดตาม", (150, 565, 330, 610)),
    node("1.9K", (450, 500, 630, 560)), node("ผู้ติดตาม", (450, 565, 630, 610)),
    node("7,412", (750, 500, 930, 560)), node("ถูกใจ", (750, 565, 930, 610)),
    node("ถูกใจ", (100, 1500, 200, 1540)),  # a word lower down, not the counts row
]
TILE = "com.zhiliaoapp.musically:id/daw"
GRID = [
    node("วิดีโอส่วนตัว", (400, 900, 700, 960)),
    node("ปักหมุด", (0, 400, 360, 440)), node("9999", (0, 800, 360, 840)),  # above the tabs: not counted
    node("", (0, 1000, 360, 1480), TILE, True), node("328", (20, 1420, 200, 1470)),
    node("", (360, 1000, 720, 1480), TILE, True), node("1.2K", (380, 1420, 560, 1470)),
    node("", (720, 1000, 1080, 1480), TILE, True),  # no number shown: left out, never guessed
]


class FakeUi(TikTokUi):
    def __init__(self, grid=GRID, videos_fail=False):
        super().__init__(adb=None, serial="S", sleep=lambda s: None, settle_s=0)
        self.screens, self.grid, self.videos_fail, self.closed = [PROFILE], grid, videos_fail, False

    def account(self, tries=None, *, require=True):
        return "shop.test"

    def read(self, *, check=True, exact=False):
        return self.screens[-1]

    def open_videos_tab(self):
        if self.videos_fail:
            raise UiStop("VIDEOS_TAB_NOT_FOUND", "no tab")
        self.screens.append(self.grid)

    def close(self):
        self.closed = True


def test_parse_count_reads_tiktok_numbers_and_nothing_else():
    assert [account_stats.parse_count(t) for t in ("1,237", "1.2K", "3.4ล้าน", "12.5หมื่น", "980", " 2m ")] == [
        1237, 1200, 3_400_000, 125_000, 980, 2_000_000]
    assert [account_stats.parse_count(t) for t in ("", "ผู้ติดตาม", "1.2x", "-5", "@123")] == [None] * 5


def test_read_profile_takes_the_counts_row_and_the_grid_below_the_tabs():
    got = account_stats.read_profile(FakeUi())
    assert got == {"account": "shop.test", "followers": 1900, "following": 405, "likes": 7412,
                   "video_views": [328, 1200]}


def test_counts_are_still_sent_when_the_videos_tab_cannot_be_read():
    got = account_stats.read_profile(FakeUi(videos_fail=True))
    assert got["followers"] == 1900 and got["video_views"] == []


class Client:
    def __init__(self, fail=False):
        self.fail, self.sent = fail, []

    def account_stats(self, session, serial, numbers):
        if self.fail:
            raise OSError("server down")
        self.sent.append((serial, numbers))


def test_read_and_send_never_raises_and_always_closes_tiktok():
    ui, client, logs = FakeUi(), Client(), []
    assert account_stats.read_and_send(client, None, ui, "HW1", logs.append) is True
    assert client.sent[0][0] == "HW1" and ui.closed
    ui = FakeUi()
    assert account_stats.read_and_send(Client(fail=True), None, ui, "HW1", logs.append) is False
    assert ui.closed and "อ่านไม่ได้" in logs[-1]


def test_stats_clock_reads_each_phone_twice_a_day_and_survives_a_restart(tmp_path):
    path = tmp_path / "stats_clock.json"
    clock = account_stats.StatsClock(path)
    assert clock.due("A", now=1_000_000)
    clock.mark("A", now=1_000_000)
    again = account_stats.StatsClock(path)  # a restart
    assert not again.due("A", now=1_000_000 + 3600) and again.due("B", now=1_000_000)
    assert again.due("A", now=1_000_000 + account_stats.STATS_EVERY_S)
    path.write_text("not json", encoding="utf-8")
    assert account_stats.StatsClock(path).due("A")
