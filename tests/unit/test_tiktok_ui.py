"""TikTok UI adapter logic (P5.4, G5-02/G5-03) against a simulated phone.

The screens are synthetic copies of the structure seen on the QA phone on 2026-10-08 (labels,
classes and bounds), with a made-up account. They check decisions, not real compatibility; the
real run is `agent.cli ui-rehearsal` on the QA phone.
"""

from __future__ import annotations

import base64
import re

import pytest

from agent.adb import Adb
from agent.thai_keyboard import IME
from agent.tiktok_ui import TikTokUi, UiStop, account_handle, classify, forbidden, parse_dump

GBOARD = "com.google.android.inputmethod.latin/com.android.inputmethod.latin.LatinIME"


def node(text="", desc="", cls="android.widget.TextView", bounds=(0, 0, 10, 10), clickable=False):
    x1, y1, x2, y2 = bounds
    return (f'<node text="{text}" resource-id="" class="{cls}" content-desc="{desc}" '
            f'clickable="{str(clickable).lower()}" bounds="[{x1},{y1}][{x2},{y2}]" />')


def screen(*nodes):
    return '<?xml version="1.0"?><hierarchy rotation="0"><node class="android.widget.FrameLayout" bounds="[0,0][720,1600]">' \
        + "".join(nodes) + "</node></hierarchy>"


PROFILE = lambda handle: screen(  # noqa: E731
    node("qa", cls="android.widget.Button", bounds=(297, 384, 423, 428), clickable=True),
    node(f"@{handle}", cls="android.widget.Button", bounds=(278, 434, 442, 474), clickable=True),
    node(desc="วิดีโอส่วนตัว", cls="android.widget.RelativeLayout", bounds=(196, 720, 360, 800), clickable=True))
SHARE = screen(node(desc="Bottom sheet", cls="android.widget.FrameLayout", bounds=(0, 862, 720, 1506)),
               node("Share on TikTok", bounds=(230, 892, 489, 936)),
               node("Video", cls="android.widget.Button", bounds=(103, 1394, 299, 1450), clickable=True),
               node("Message", cls="android.widget.Button", bounds=(421, 1394, 617, 1450), clickable=True))
EDITOR = screen(node("Story ของคุณ", bounds=(126, 1435, 331, 1477)), node("ถัดไป", bounds=(493, 1434, 574, 1477)))


def post_screen(caption="เพิ่มคำอธิบาย...", visibility="ทุกคนสามารถดูโพสต์นี้ได้", keyboard=False):
    post_bounds = (566, 87, 688, 150) if keyboard else (368, 1394, 696, 1482)
    return screen(
        node(caption, cls="android.widget.EditText", bounds=(32, 179, 432, 477), clickable=True),
        node(desc=visibility, cls="android.widget.Button", bounds=(0, 913, 720, 1025), clickable=True),
        node(visibility, bounds=(88, 947, 483, 991)),
        node(desc="บันทึกไปยังแบบร่าง", cls="android.widget.Button", bounds=(24, 1394, 352, 1482), clickable=True),
        node(desc="โพสต์", cls="android.widget.Button", bounds=post_bounds, clickable=True))


VIS_SHEET = screen(node(desc="แผ่นล่าง", cls="android.widget.FrameLayout", bounds=(0, 864, 720, 1506)),
                   node(desc="ทุกคน", cls="android.view.ViewGroup", bounds=(16, 1081, 704, 1187), clickable=True),
                   node(desc="เฉพาะคุณเท่านั้น", cls="android.view.ViewGroup", bounds=(16, 1353, 704, 1462), clickable=True),
                   node("เฉพาะคุณเท่านั้น", bounds=(72, 1385, 296, 1430)))


class FakeTikTok:
    """A small state machine: what is on screen, and what a press at x,y does there."""

    def __init__(self, handle="qa_account", first="feed", share_lands_on=SHARE, typed=None):
        self.handle, self.state, self.share_lands_on, self.typed_override = handle, first, share_lands_on, typed
        self.caption, self.visibility, self.ime = None, "ทุกคนสามารถดูโพสต์นี้ได้", GBOARD
        self.presses, self.keyboard, self.stopped, self.lose_first = [], False, False, False

    def xml(self) -> str:
        if self.state == "feed":
            return ""  # the For You feed cannot be dumped (video playing)
        if self.state == "profile":
            return PROFILE(self.handle)
        if self.state == "share":
            return self.share_lands_on
        if self.state == "editor":
            return EDITOR
        if self.state == "vis_sheet":
            return VIS_SHEET
        return post_screen(self.caption or "เพิ่มคำอธิบาย...", self.visibility, self.keyboard)

    def tap(self, x: int, y: int) -> None:
        self.presses.append((self.state, x, y))
        hit = [n for n in parse_dump(self.xml()) if n.contains(x, y) and n.label]
        labels = {n.label for n in hit}
        if self.state == "feed" and y > 1400 and x > 600:
            self.state = "profile"
        elif "Video" in labels:
            self.state = "editor"
        elif "ถัดไป" in labels:
            self.state = "post"
        elif self.state == "post" and any("ดูโพสต์นี้ได้" in label for label in labels):
            self.state = "vis_sheet"
        elif self.state == "vis_sheet" and "เฉพาะคุณเท่านั้น" in labels:
            self.visibility, self.state = "เฉพาะคุณเท่านั้นที่ดูโพสต์นี้ได้", "post"
        elif any(n.cls.endswith("EditText") for n in hit):
            self.keyboard = True
        elif "โพสต์" in labels:
            raise AssertionError("the adapter pressed Post")

    def run(self, args: list[str]) -> str:
        cmd = args[3] if len(args) > 3 else ""
        if m := re.match(r"input swipe (\d+) (\d+) \d+ \d+ 120", cmd):
            self.tap(int(m.group(1)), int(m.group(2)))
        elif cmd.startswith("cat "):
            return self.xml()
        elif cmd.startswith("monkey "):
            self.state = "feed"
        elif cmd.startswith("am start -a android.intent.action.SEND"):
            self.state = "share"
        elif cmd == "pm list packages":
            return "package:com.ss.android.ugc.trill\npackage:app.punpun.keyboard\n"
        elif cmd.startswith("ime enable "):
            assert cmd.split()[2] == IME
        elif cmd.startswith("ime set "):
            self.ime = cmd.split()[2]
        elif cmd == "settings get secure default_input_method":
            return self.ime + "\n"
        elif cmd.startswith("am broadcast -a ADB_INPUT_B64"):
            assert self.ime == IME
            if self.lose_first:  # the keyboard was not listening yet
                self.lose_first = False
                return ""
            text = base64.b64decode(cmd.split()[-1]).decode()
            self.caption = self.typed_override if self.typed_override is not None else text
        elif cmd.startswith("dumpsys input_method"):
            return f"mInputShown={'true' if self.keyboard else 'false'}\n"
        elif cmd == "input keyevent KEYCODE_BACK":
            if not self.keyboard:
                raise AssertionError("BACK without a keyboard would leave the post screen")
            self.keyboard = False
        elif cmd.startswith("am force-stop"):
            self.stopped = True
        elif cmd == "wm size":
            return "Physical size: 720x1600\n"
        elif cmd.startswith("dumpsys window"):
            return "  mCurrentFocus=Window{1 u0 com.ss.android.ugc.trill/Fake}\n"
        return ""


def ui_for(phone):
    return TikTokUi(Adb(phone.run), "QA1", sleep=lambda s: None, settle_s=0, wait_s=0)


def test_full_rehearsal_reaches_the_ready_screen_without_pressing_post():
    phone = FakeTikTok()
    ui = ui_for(phone)
    assert ui.check_account("@QA_account") == "qa_account"  # handles compare case-insensitively
    ui.open_post_screen("60")
    ui.set_only_me()
    caption = "ซ้อมระบบ punpun 🎬 ห้ามเผยแพร่ #ทดสอบ #punpun"
    ui.type_caption(caption)
    ui.close()
    assert phone.caption == caption and phone.visibility.startswith("เฉพาะคุณ")
    assert phone.ime == GBOARD and phone.stopped and not phone.keyboard


def test_wrong_account_stops_before_anything_is_opened():
    phone = FakeTikTok(handle="someone_else")
    with pytest.raises(UiStop) as err:
        ui_for(phone).check_account("qa_account")
    assert err.value.code == "ACCOUNT_MISMATCH"
    assert all(state in ("feed", "profile") for state, *_ in phone.presses)


def test_an_unreadable_account_stops_before_anything_is_opened():  # T15
    class NoHandle(FakeTikTok):
        def xml(self):
            return screen(node("qa", bounds=(297, 384, 423, 428))) if self.state == "profile" else super().xml()

    phone = NoHandle()
    with pytest.raises(UiStop) as err:
        ui_for(phone).check_account("qa_account")
    assert err.value.code == "ACCOUNT_UNREADABLE"
    assert all(state in ("feed", "profile") for state, *_ in phone.presses) and phone.caption is None


@pytest.mark.parametrize("texts, code", [
    (["เข้าสู่ระบบ TikTok", "ใช้โทรศัพท์หรืออีเมล"], "LOGIN_REQUIRED"),
    (["Log in to TikTok", "Use phone or email"], "LOGIN_REQUIRED"),
    (["ลากชิ้นส่วนให้ตรงกับภาพ"], "CAPTCHA"),
    (["Verify you are human", "Drag the slider"], "CAPTCHA"),
])
def test_login_walls_and_captcha_stop_the_attempt(texts, code):
    wall = screen(*[node(t, bounds=(0, 100 * i, 720, 100 * i + 80)) for i, t in enumerate(texts)])
    phone = FakeTikTok(share_lands_on=wall)
    with pytest.raises(UiStop) as err:
        ui_for(phone).open_post_screen("60")
    assert err.value.code == code
    assert classify(parse_dump(wall)) == code


def test_an_unexpected_screen_is_never_guessed_at():
    phone = FakeTikTok(share_lands_on=screen(node("อัปเดตแอป", bounds=(0, 0, 720, 100))))
    with pytest.raises(UiStop) as err:
        ui_for(phone).open_post_screen("60")
    assert err.value.code == "UNKNOWN_SCREEN"


def test_caption_that_does_not_match_stops_and_the_keyboard_is_restored():
    phone = FakeTikTok(typed="ซ้อมระบบ punpun ห้ามเผยแพร่")  # emoji lost on the way
    ui = ui_for(phone)
    ui.open_post_screen("60")
    with pytest.raises(UiStop) as err:
        ui.type_caption("ซ้อมระบบ punpun 🎬 ห้ามเผยแพร่")
    assert err.value.code == "CAPTION_MISMATCH" and phone.ime == GBOARD
    assert "ซ้อมระบบ punpun ห้ามเผยแพร่" in err.value.detail  # what the screen showed, for whoever checks


def test_a_caption_lost_while_the_keyboard_starts_is_typed_again():  # QA phone, 2026-10-12
    phone = FakeTikTok()
    phone.lose_first = True
    ui = ui_for(phone)
    ui.open_post_screen("60")
    ui.type_caption("ตอนที่ 1/3 #ละคร")
    assert phone.caption == "ตอนที่ 1/3 #ละคร" and phone.ime == GBOARD


def test_post_draft_story_and_shop_are_never_pressed():
    nodes = parse_dump(post_screen(keyboard=True) + "")
    assert [n.label for n in nodes if forbidden(n)] == ["บันทึกไปยังแบบร่าง", "โพสต์"]
    assert forbidden(parse_dump(EDITOR)[1])  # "Story ของคุณ"
    for label in ("Post", "ร้านค้า", "Shop", "LIVE", "ร่าง"):
        assert forbidden(parse_dump(screen(node(label)))[1])
    phone = FakeTikTok(first="post")
    phone.state = "post"
    with pytest.raises(UiStop) as err:
        ui_for(phone).press("โพสต์")
    assert err.value.code == "REFUSED_ELEMENT" and phone.presses == []


def test_a_press_is_refused_when_post_has_moved_under_the_point():
    """With the keyboard up, Post sits top-right. A target sharing that spot is never pressed."""
    overlapped = screen(node("ถัดไป", bounds=(560, 80, 700, 160)),
                        node(desc="โพสต์", cls="android.widget.Button", bounds=(566, 87, 688, 150), clickable=True))
    phone = FakeTikTok(share_lands_on=overlapped, first="share")
    with pytest.raises(UiStop) as err:
        ui_for(phone).press("ถัดไป")
    assert err.value.code == "REFUSED_ELEMENT" and phone.presses == []


def test_account_handle_and_profile_tab_fallback():
    assert account_handle(parse_dump(PROFILE("Patsy.Test_1"))) == "patsy.test_1"
    assert account_handle(parse_dump(SHARE)) is None
    phone = FakeTikTok()
    assert ui_for(phone).account() == "qa_account"
    assert phone.presses[0][0] == "feed"  # feed has no dump: bottom-right tab, then verified on Profile


# --- the authorized post (Q-29) ---------------------------------------------------------------

def test_a_grant_is_used_once_and_recorded_before_use(tmp_path):
    from agent.authorization import GrantRefused, take

    ledger = tmp_path / "authorizations.json"
    grant = take(ledger, "Q-29", 1, "post A")
    assert (grant.decision, grant.number) == ("Q-29", 1)
    with pytest.raises(GrantRefused):
        take(ledger, "Q-29", 1, "post B")
    with pytest.raises(GrantRefused):
        take(ledger, "", 1, "no decision")


def ready_to_post(caption):
    phone = FakeTikTok()
    ui = ui_for(phone)
    ui.open_post_screen("60")
    ui.set_only_me()
    ui.type_caption(caption)
    return phone, ui


def test_submit_needs_a_grant_and_the_expected_screen(tmp_path):
    from agent.authorization import take

    caption = "ทดสอบ cf123456"
    phone, ui = ready_to_post(caption)
    with pytest.raises(UiStop) as err:
        ui.submit(object(), caption)
    assert err.value.code == "NO_GRANT"
    grant = take(tmp_path / "a.json", "Q-TEST", 1, "unit")
    with pytest.raises(UiStop) as err:
        ui.submit(grant, caption + " changed")
    assert err.value.code == "CAPTION_MISMATCH"
    phone.keyboard = True
    with pytest.raises(UiStop) as err:
        ui.submit(grant, caption)
    assert err.value.code == "KEYBOARD_SHOWN"
    phone.keyboard = False
    phone.tap = lambda x, y: phone.presses.append(("POST", x, y))
    ui.submit(grant, caption)
    assert phone.presses[-1] == ("POST", 532, 1438)  # the bottom Post button, nothing else


def test_tiktok_is_opened_again_when_it_is_not_in_front():
    """QA phone, 2026-10-11: the last reading was the home screen (TikTok was no longer in front)."""
    class Behind(FakeTikTok):
        launches = 0

        def run(self, args):
            cmd = args[3] if len(args) > 3 else ""
            if cmd.startswith("monkey "):
                self.launches += 1
                self.state = "home" if self.launches == 1 else "feed"  # the first launch did not stick
                return ""
            if cmd.startswith("dumpsys window"):
                app = "com.miui.home/.launcher.Launcher" if self.state == "home" else "com.ss.android.ugc.trill/Fake"
                return f"  mCurrentFocus=Window{{1 u0 {app}}}\n"
            return super().run(args)

        def xml(self):
            return screen(node("ตัวจัดการไฟล์", bounds=(22, 99, 191, 268))) if self.state == "home" else super().xml()

    phone = Behind()
    assert ui_for(phone).account() == "qa_account"
    assert phone.launches == 2 and all(state != "home" for state, *_ in phone.presses)  # never tapped the home screen


def test_a_forbidden_container_behind_the_target_does_not_block_it_but_a_forbidden_control_does():
    """QA phone, 2026-10-11: after a post the feed's "LIVE" view (0,436)-(720,1506) lies behind the
    tab bar, so checking the result was refused at the Profile tab. A container that wholly encloses
    the target is not what a tap hits; anything forbidden of the target's size or smaller still blocks."""
    from agent.tiktok_ui import encloses

    tab = node("โปรไฟล์", bounds=(576, 1408, 720, 1506), clickable=True)
    live = node(desc="LIVE", bounds=(0, 436, 720, 1506))
    parsed = parse_dump(screen(live, tab))
    assert encloses(parsed[1], parsed[2]) and not encloses(parsed[2], parsed[1])  # [0] is the root

    class Feed(FakeTikTok):
        def __init__(self, extra):
            super().__init__(first="feed")
            self.extra = extra

        def xml(self):
            if self.state == "feed":
                return screen(self.extra, tab)
            return super().xml()

        def tap(self, x, y):
            if self.state == "feed" and 576 <= x < 720 and 1408 <= y < 1506:  # the Profile tab
                self.state = "profile"
            self.presses.append((self.state, x, y))

    phone = Feed(live)
    ui_for(phone).press("โปรไฟล์")
    assert phone.state == "profile"

    for blocker in (node(desc="LIVE", bounds=(600, 1420, 700, 1500)),   # smaller, on top of the tab
                    node("ร้านค้า", bounds=(560, 1400, 700, 1500))):     # overlaps, does not enclose
        phone = Feed(blocker)
        with pytest.raises(UiStop) as err:
            ui_for(phone).press("โปรไฟล์")
        assert err.value.code == "REFUSED_ELEMENT" and phone.state == "feed"



class Shell:
    def __init__(self):
        self.commands = []

    def shell(self, serial, command):
        self.commands.append(command)
        return ""


def test_verification_trusts_the_marker_not_a_full_grid_and_looks_again_while_uploading(monkeypatch):
    # QA phone, 2026-10-11: Profile shows 5 private tiles; the 6th post read 5 -> 5 and became UNKNOWN.
    phone = Shell()
    ui = TikTokUi(phone, "S", sleep=lambda s: None)
    monkeypatch.setattr(ui, "account", lambda **kw: "qa")
    monkeypatch.setattr(ui, "private_count", lambda: 5)
    monkeypatch.setattr(ui, "read", lambda **kw: [])
    with pytest.raises(UiStop) as stop:  # nothing on the private tab: looked 4 times, then unknown
        ui.verify_private_post("cfabc123", 5)
    assert stop.value.code == "VERIFY_MARKER" and phone.commands.count("input keyevent KEYCODE_BACK") == 3

    seen = iter([UiStop("VERIFY_MARKER", "still uploading"), UiStop("VERIFY_UNREADABLE", "x"), {"value": "cfabc123"}])

    def newest(marker, before):
        result = next(seen)
        if isinstance(result, UiStop):
            raise result
        return result

    monkeypatch.setattr(ui, "_newest_private_has", newest)
    assert ui.verify_private_post("cfabc123", 5) == {"value": "cfabc123"}


def test_fewer_private_videos_than_before_stops_at_once(monkeypatch):
    phone = Shell()
    ui = TikTokUi(phone, "S", sleep=lambda s: None)
    monkeypatch.setattr(ui, "account", lambda **kw: "qa")
    monkeypatch.setattr(ui, "private_count", lambda: 3)
    with pytest.raises(UiStop) as stop:
        ui.verify_private_post("cfabc123", 5)
    assert stop.value.code == "VERIFY_COUNT" and "input keyevent KEYCODE_BACK" not in phone.commands


def test_an_unreadable_account_right_after_post_is_read_again_not_unknown(monkeypatch):
    # tx2, 2026-10-13: b7f207dd became UNKNOWN on the first ACCOUNT_UNREADABLE after Post.
    phone = Shell()
    ui = TikTokUi(phone, "S", sleep=lambda s: None)
    seen = iter([UiStop("ACCOUNT_UNREADABLE", "covered"), UiStop("ACCOUNT_UNREADABLE", "covered"),
                 {"value": "cfabc123"}])

    def newest(marker, before):
        result = next(seen)
        if isinstance(result, UiStop):
            raise result
        return result

    monkeypatch.setattr(ui, "_newest_private_has", newest)
    assert ui.verify_private_post("cfabc123", 5) == {"value": "cfabc123"}
    assert phone.commands.count("input keyevent KEYCODE_BACK") == 2

    seen = iter([UiStop("ACCOUNT_UNREADABLE", "covered")] * 4)
    with pytest.raises(UiStop) as stop:  # still unreadable after 4 looks: UNKNOWN, never guessed
        ui.verify_private_post("cfabc123", 5)
    assert stop.value.code == "ACCOUNT_UNREADABLE"


def test_with_the_account_check_off_another_account_is_used_and_not_compared():
    # Q-48: an admin turned the Workspace's account check off.
    phone = FakeTikTok(handle="someone_else")
    ui = ui_for(phone)
    with pytest.raises(UiStop) as stop:
        ui.check_account("qa_account")
    assert stop.value.code == "ACCOUNT_MISMATCH"  # on (the default): refused
    ui.account_check = False
    assert ui.check_account("qa_account") == "someone_else"
    assert ui.check_account(None) == "someone_else"  # no account set for the phone: fine when off


def test_with_the_account_check_on_a_phone_without_an_account_never_posts():
    with pytest.raises(UiStop) as stop:
        ui_for(FakeTikTok()).check_account(None)
    assert stop.value.code == "ACCOUNT_NOT_SET"
