"""The second screen reader (PO 2026-10-13): screens `uiautomator dump` cannot read (tx1, shop countdown)."""

from __future__ import annotations

import hashlib
import io
import json
import re

import pytest

from agent import screen_reader
from agent.adb import Adb
from agent.screen_reader import ReaderError, U2Reader
from agent.tiktok_ui import TikTokUi, UiStop

JAR = b"the u2 jar"
SHOP_PROFILE = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node text="@jk.mickey" content-desc="" resource-id="" class="android.widget.TextView" clickable="false" bounds="[290,435][430,475]" />
<node text="TikTok Shop สำหรับครีเอเตอร์" content-desc="" resource-id="" class="android.widget.TextView" clickable="true" bounds="[90,820][450,860]" />
</hierarchy>"""


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Phone:
    """adb + the server on the phone: what was run, and what the server answers."""

    def __init__(self, on_phone: bytes | None = None, answer=SHOP_PROFILE, starts=True):
        self.on_phone, self.answer, self.starts = on_phone, answer, starts
        self.commands, self.requests, self.running, self.forwards = [], [], False, set()

    def shell(self, serial, command):
        self.commands.append(command)
        if command.startswith("sha256sum"):
            return f"{hashlib.sha256(self.on_phone).hexdigest()}  {screen_reader.REMOTE}\n" if self.on_phone else ""
        if "app_process" in command:
            assert "-p 9008" in command and command.startswith(f"CLASSPATH={screen_reader.REMOTE} ")
            self.running = self.starts
        if command.startswith("pkill"):
            self.running = False
        return ""

    def push(self, serial, local, remote):
        assert remote == screen_reader.REMOTE
        self.on_phone = local.read_bytes()

    def forward(self, serial, port):
        assert port == 9008
        self.forwards.add(50123)
        return 50123

    def forward_remove(self, serial, port):
        self.forwards.discard(port)

    def http(self, request, timeout):
        url = request if isinstance(request, str) else request.full_url
        assert url.startswith("http://127.0.0.1:50123/")
        if not self.running:
            raise ConnectionRefusedError("nothing listening")
        if url.endswith("/ping"):
            return Response(b"pong")
        body = json.loads(request.data)
        self.requests.append(body)
        return Response(json.dumps({"jsonrpc": "2.0", "id": 1, "result": self.answer}).encode())


@pytest.fixture
def jar(tmp_path):
    path = tmp_path / "u2.jar"
    path.write_bytes(JAR)
    return lambda: path


def reader(phone, jar):
    return U2Reader(phone, "S", jar=jar, http=phone.http, sleep=lambda s: None, start_timeout_s=0.05)


def test_it_pushes_the_checked_jar_starts_once_and_reads_only_the_window_in_front(jar):
    phone = Phone()
    r = reader(phone, jar)
    assert "@jk.mickey" in r.dump() and "@jk.mickey" in r.dump()
    assert sum("app_process" in c for c in phone.commands) == 1  # started once, then reused
    assert phone.requests[0]["method"] == "dumpWindowHierarchy" and phone.requests[0]["params"] == [False, 50, True]
    r.stop()
    assert not phone.running and not phone.forwards and r.port is None


def test_a_jar_already_on_the_phone_is_not_pushed_again(jar, monkeypatch):
    phone = Phone(on_phone=JAR)
    monkeypatch.setattr(phone, "push", lambda *a: pytest.fail("pushed again"))
    reader(phone, jar).dump()


def test_a_server_that_never_answers_is_stopped_and_reported(jar):
    phone = Phone(starts=False)
    r = reader(phone, jar)
    with pytest.raises(ReaderError, match="did not start"):
        r.dump()
    assert not phone.forwards and phone.commands[-1].startswith("pkill")


def test_an_error_from_the_server_is_not_a_reading(jar):
    phone = Phone(answer=None)
    with pytest.raises(ReaderError):
        reader(phone, jar).dump()


def test_only_the_checked_jar_is_kept(tmp_path):
    def opener(data):
        return lambda url, timeout: Response(data)

    with pytest.raises(ReaderError, match="not the checked file"):
        screen_reader.download(tmp_path, opener(b"something else"))
    assert not list(tmp_path.iterdir())


def test_the_pinned_jar_is_downloaded_once(tmp_path, monkeypatch):
    monkeypatch.setattr(screen_reader, "JAR_SHA256", hashlib.sha256(JAR).hexdigest())
    path = screen_reader.download(tmp_path, lambda url, timeout: Response(JAR))
    assert path.read_bytes() == JAR
    assert screen_reader.download(tmp_path, lambda url, timeout: pytest.fail("downloaded again")) == path


class ShopPhone:
    """tx1, 2026-10-13: Profile on the shop tab; `uiautomator dump` says "could not get idle state"."""

    def __init__(self):
        self.stock = []

    def run(self, args):
        cmd = args[3] if len(args) > 3 else ""
        if cmd.startswith("uiautomator dump"):
            self.stock.append(cmd)
            return "ERROR: could not get idle state.\n"
        if cmd.startswith("cat "):
            return "cat: /sdcard/cf_ui.xml: No such file or directory\n"
        if cmd.startswith("dumpsys window"):
            return "  mCurrentFocus=Window{1 u0 com.ss.android.ugc.trill/Fake}\n"
        if cmd == "wm size":
            return "Physical size: 720x1600\n"
        return ""


class FakeReader:
    def __init__(self):
        self.dumps, self.stopped = 0, False

    def dump(self, all_windows=False):
        self.dumps += 1
        return SHOP_PROFILE

    def stop(self):
        self.stopped = True


def test_a_screen_that_never_stops_moving_is_read_by_the_second_reader_but_a_caption_never_is():
    phone, second = ShopPhone(), FakeReader()
    ui = TikTokUi(Adb(phone.run), "S", sleep=lambda s: None, settle_s=0, wait_s=0, reader=second)
    assert ui.account() == "jk.mickey" and ui.reader_on
    ui.read()  # `uiautomator dump` takes ~12 s to give up: once switched, it is not tried again
    assert len(phone.stock) == 1 and second.dumps == 2
    # A caption check: the second reader shows emoji as "..", so it is stopped and only
    # `uiautomator dump` counts; here that reads nothing, so the caption is not found (never guessed).
    assert ui.read(exact=True) == [] and second.stopped and not ui.reader_on
    assert len(phone.stock) == 2 and second.dumps == 2
    second.stopped = False
    ui.read()
    ui.close()
    assert second.stopped and not ui.reader_on

def test_without_the_second_reader_it_still_stops_rather_than_guess():
    phone = ShopPhone()
    ui = TikTokUi(Adb(phone.run), "S", sleep=lambda s: None, settle_s=0, wait_s=0)
    with pytest.raises(UiStop) as stop:
        ui.account(tries=2)
    assert stop.value.code == "ACCOUNT_UNREADABLE"


def test_a_failing_second_reader_reads_as_nothing_and_the_account_is_never_guessed():
    class Broken(FakeReader):
        def dump(self, all_windows=False):
            raise ReaderError("no network")

    ui = TikTokUi(Adb(ShopPhone().run), "S", sleep=lambda s: None, settle_s=0, wait_s=0, reader=Broken())
    with pytest.raises(UiStop) as stop:
        ui.account(tries=2)
    assert stop.value.code == "ACCOUNT_UNREADABLE"


def test_the_agent_builds_its_tiktok_steps_with_the_second_reader():
    ui = TikTokUi.for_phone(Adb(ShopPhone().run), "S")
    assert isinstance(ui.reader, U2Reader) and re.fullmatch(r"[0-9a-f]{64}", screen_reader.JAR_SHA256)


def test_on_profile_with_the_handle_covered_it_waits_once_then_presses_profile_again():
    # tx2, 2026-10-13: right after Post the header stayed covered while the Agent only waited.
    covered = SHOP_PROFILE.replace('<node text="@jk.mickey"', '<node text="332"').replace(
        "</hierarchy>", '<node text="กำลังติดตาม" content-desc="" resource-id="" class="android.widget.TextView" '
                        'clickable="false" bounds="[59,544][259,576]" /><node text="ผู้ติดตาม" content-desc="" '
                        'resource-id="" class="android.widget.TextView" clickable="false" bounds="[312,542][409,576]" />'
                        '<node text="โปรไฟล์" content-desc="" resource-id="" class="android.widget.FrameLayout" '
                        'clickable="true" bounds="[576,1408][720,1506]" /></hierarchy>')
    commands = []

    class Banner(FakeReader):
        def dump(self, all_windows=False):  # the header shows again once Profile is pressed
            if all_windows:
                return SHOP_PROFILE.replace("@jk.mickey", "")
            return SHOP_PROFILE if any(c.startswith("input") for c in commands) else covered

    phone = ShopPhone()
    run = phone.run
    phone.run = lambda args: commands.append(args[3] if len(args) > 3 else "") or run(args)
    ui = TikTokUi(Adb(phone.run), "S", sleep=lambda s: None, settle_s=0, wait_s=0, reader=Banner())
    assert ui.account() == "jk.mickey"
    assert [c for c in commands if c.startswith("input")] == ["input swipe 648 1457 648 1457 120"]


def node_xml(text, bounds, cls="android.widget.TextView", clickable=False):
    return (f'<node text="{text}" content-desc="" resource-id="" class="{cls}" '
            f'clickable="{str(clickable).lower()}" bounds="{bounds}" />')


COVERED = ("<hierarchy>" + node_xml("332", "[59,504][259,548]") + node_xml("กำลังติดตาม", "[59,544][259,576]")
           + node_xml("ผู้ติดตาม", "[312,542][409,576]")
           + node_xml("โปรไฟล์", "[576,1408][720,1506]", "android.widget.FrameLayout", True) + "</hierarchy>")
# tx1, 2026-10-13, all windows: the banner window (ids oj8/oj4/oj5), above the avatar's "สร้าง Story".
BANNER = ("<hierarchy>" + node_xml("สร้าง Story", "[276,180][444,350]", "android.widget.ImageView", True)
          + node_xml("", "[16,94][704,312]", "android.widget.FrameLayout")
          + node_xml("", "[160,118][680,284]", "android.widget.LinearLayout")
          + node_xml("แก้ไขวิดีโอที่ยังไม่ได้โพสต์ของคุณต่อหรือไม่", "[160,118][680,200]")
          + node_xml("", "[160,220][680,284]", "android.widget.LinearLayout")
          + node_xml("ยกเลิก", "[160,220][412,284]", "android.widget.Button", True)
          + node_xml("ยืนยัน", "[428,220][680,284]", "android.widget.Button", True) + "</hierarchy>")


class BannerPhone(ShopPhone):
    def __init__(self, stays=False):
        super().__init__()
        self.banner, self.stays, self.presses = True, stays, []

    def run(self, args):
        cmd = args[3] if len(args) > 3 else ""
        if m := re.match(r"input swipe (\d+) (\d+)", cmd):
            self.presses.append((int(m.group(1)), int(m.group(2))))
            if (160 <= self.presses[-1][0] < 412 and 220 <= self.presses[-1][1] < 284) and not self.stays:
                self.banner = False
        return super().run(args)


class BannerReader(FakeReader):
    def __init__(self, phone):
        super().__init__()
        self.phone = phone

    def dump(self, all_windows=False):
        if self.phone.banner:
            return BANNER if all_windows else COVERED
        return SHOP_PROFILE


def test_the_continue_editing_banner_is_closed_with_its_cancel_button_only():
    phone = BannerPhone()
    ui = TikTokUi(Adb(phone.run), "S", sleep=lambda s: None, settle_s=0, wait_s=0, reader=BannerReader(phone))
    assert ui.account() == "jk.mickey"
    assert phone.presses == [(286, 252)]  # ยกเลิก, never ยืนยัน, never Profile again


def test_a_banner_that_stays_after_cancel_stops_the_post():
    phone = BannerPhone(stays=True)
    ui = TikTokUi(Adb(phone.run), "S", sleep=lambda s: None, settle_s=0, wait_s=0, reader=BannerReader(phone))
    with pytest.raises(UiStop) as stop:
        ui.account()
    assert stop.value.code == "RESUME_BANNER" and phone.presses == [(286, 252)]


def test_a_cancel_button_outside_that_banner_is_never_pressed():
    phone = BannerPhone()
    reader = BannerReader(phone)
    other = BANNER.replace("แก้ไขวิดีโอที่ยังไม่ได้โพสต์ของคุณต่อหรือไม่", "ลบวิดีโอนี้หรือไม่")
    reader.dump = lambda all_windows=False: other if all_windows else COVERED
    ui = TikTokUi(Adb(phone.run), "S", sleep=lambda s: None, settle_s=0, wait_s=0, reader=reader)
    with pytest.raises(UiStop) as stop:
        ui.account(tries=2)
    assert stop.value.code == "ACCOUNT_UNREADABLE" and (286, 252) not in phone.presses  # Profile only


def test_a_shop_card_behind_the_profile_tab_means_nothing_is_pressed_and_it_never_guesses():
    # tx1, 2026-10-13: "Yatawee Shop" scrolled behind the tab bar, right under the Profile tab.
    covered = COVERED.replace("</hierarchy>", node_xml("Yatawee Shop", "[384,1429][688,1461]",
                                                       "com.lynx.tasm.behavior.ui.LynxFlattenUI") + "</hierarchy>")
    phone = BannerPhone()
    phone.banner = False
    reader = FakeReader()
    reader.dump = lambda all_windows=False: covered if not all_windows else SHOP_PROFILE.replace("@jk.mickey", "")
    ui = TikTokUi(Adb(phone.run), "S", sleep=lambda s: None, settle_s=0, wait_s=0, reader=reader)
    with pytest.raises(UiStop) as stop:
        ui.account(tries=4)
    assert stop.value.code == "ACCOUNT_UNREADABLE" and phone.presses == []
