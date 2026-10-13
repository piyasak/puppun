"""TikTok UI steps up to, never including, Post (P5.4, Q-27; docs/runbooks/tiktok-posting-poc.md).

What this module does on the phone:
- read the logged-in account on Profile and refuse a different one (FR-16, G5-03);
- open the exact verified file through the share intent (never the gallery grid);
- "Video" -> "ถัดไป"/"Next" -> visibility "Only you" -> type the approved Thai caption via
  our Thai keyboard (punpun Thai input, agent.thai_keyboard) and check it character for character;
- stop with NEEDS_ACTION on a login wall, CAPTCHA or any screen it does not expect;
- close TikTok (force-stop) so nothing is posted or kept.

`press` refuses Post, Story, Draft and anything in the shop. Post is pressed only by `submit`, once,
with a grant (Q-29 local ledger or a Q-42 server grant, after the server accepted SUBMITTING) and only
on a post screen showing the exact caption and "only you". Every press re-reads the screen first and checks what is really under the
point: with the keyboard up, TikTok moves "โพสต์" to the top-right corner (QA phone, 2026-10-08),
so a position from an older reading can land on a different control.

Learned on the QA phone (POCO 25078PC3EG, TikTok 40.0.0, 2026-10-08):
- `uiautomator dump` fails on the For You feed ("could not get idle state": the video never stops);
  Profile, the share sheet, the editor and the post screen dump fine. A screen that never stops moving
  (tx1, 2026-10-13: Profile on the TikTok Shop tab, a countdown) is read with agent.screen_reader instead.
- an old dump file stays on the phone, so it is deleted before every new dump;
- the share sheet can be in English ("Share on TikTok" / "Video") even when the rest is Thai;
- choosing "เฉพาะคุณเท่านั้น" closes the visibility sheet by itself: pressing BACK there would
  leave the post screen.
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from xml.etree import ElementTree

from agent import thai_keyboard
from agent.adb import Adb, AdbError

PACKAGE = "com.ss.android.ugc.trill"
SHARE_ACTIVITY = f"{PACKAGE}/com.ss.android.ugc.aweme.share.SystemShareActivity"
DUMP = "/sdcard/cf_ui.xml"

# Never pressed, whatever matched: exact labels and fragments (Thai + English builds).
FORBIDDEN_EXACT = {"โพสต์", "post", "โพสต์เลย", "post now", "ส่ง", "send", "ร่าง", "draft", "drafts"}
FORBIDDEN_FRAGMENTS = ("story", "สตอรี่", "shop", "ร้านค้า", "ซื้อ", "buy", "ตะกร้า", "cart", "live", "ไลฟ์",
                       "แบบร่าง", "บันทึกไปยัง", "save to")

LOGIN_MARKERS = ("เข้าสู่ระบบ", "log in", "ลงทะเบียน", "sign up", "ใช้โทรศัพท์หรืออีเมล", "use phone or email")
CAPTCHA_MARKERS = ("captcha", "ยืนยันว่าคุณไม่ใช่", "verify you", "ลากชิ้นส่วน", "drag the slider", "เลือก 2 วัตถุ",
                   "select 2 objects", "ตรวจสอบความปลอดภัย", "security check")
VISIBILITY_ROW = ("ดูโพสต์นี้ได้", "can view this post", "can watch this")
ONLY_ME = ("เฉพาะคุณ", "only you", "only me")
# TikTok closed in the editor (the Agent force-stops it after a rehearsal or a failed attempt) asks this
# in a floating banner that hides the Profile header from both readers (tx1, 2026-10-13, > 3 minutes).
RESUME_BANNER = ("แก้ไขวิดีโอที่ยังไม่ได้โพสต์ของคุณต่อหรือไม่",)
RESUME_CANCEL = ("ยกเลิก",)  # PO 2026-10-13: press ยกเลิก on that banner (the unposted edit may be dropped)


class UiStop(Exception):
    """Stop the attempt with NEEDS_ACTION; the code goes to the server, the detail to the local log."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Node:
    text: str
    desc: str
    rid: str
    cls: str
    clickable: bool
    bounds: tuple[int, int, int, int]

    @property
    def label(self) -> str:
        return (self.text or self.desc).strip()

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    def contains(self, x: int, y: int) -> bool:
        x1, y1, x2, y2 = self.bounds
        return x1 <= x < x2 and y1 <= y < y2

    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.bounds
        return (x2 - x1) * (y2 - y1)


_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def parse_dump(xml: str) -> list[Node]:
    try:
        root = ElementTree.fromstring(xml[xml.index("<"):])
    except (ValueError, ElementTree.ParseError):
        return []
    nodes = []
    for el in root.iter("node"):
        m = _BOUNDS.match(el.get("bounds", ""))
        if m:
            nodes.append(Node(el.get("text", ""), el.get("content-desc", ""), el.get("resource-id", ""),
                              el.get("class", ""), el.get("clickable") == "true", tuple(int(v) for v in m.groups())))
    return nodes


def forbidden(node: Node) -> bool:
    for value in (node.text, node.desc):
        v = value.strip().lower()
        if v and (v in FORBIDDEN_EXACT or any(f in v for f in FORBIDDEN_FRAGMENTS)):
            return True
    return False


def classify(nodes: list[Node]) -> str | None:
    """LOGIN_REQUIRED / CAPTCHA when such a screen is showing, else None."""
    labels = [n.label.lower() for n in nodes if n.label]
    if any(m in label for label in labels for m in CAPTCHA_MARKERS):
        return "CAPTCHA"
    if any(m in label for label in labels for m in LOGIN_MARKERS) and account_handle(nodes) is None:
        return "LOGIN_REQUIRED"
    return None


def account_handle(nodes: list[Node]) -> str | None:
    """The @handle shown on the Profile screen."""
    for n in nodes:
        if re.fullmatch(r"@[A-Za-z0-9_.]{2,24}", n.label):
            return n.label[1:].lower()
    return None


def under(nodes: list[Node], x: int, y: int) -> list[Node]:
    """Every labelled node containing the point, smallest first."""
    return sorted((n for n in nodes if n.contains(x, y) and n.label), key=lambda n: n.area)


def encloses(outer: Node, inner: Node) -> bool:
    ox1, oy1, ox2, oy2 = outer.bounds
    ix1, iy1, ix2, iy2 = inner.bounds
    return ox1 <= ix1 and oy1 <= iy1 and ix2 <= ox2 and iy2 <= oy2


def visibility_row(nodes: list[Node]) -> Node | None:
    return next((n for n in nodes if any(m in n.label.lower() for m in VISIBILITY_ROW)), None)


class TikTokUi:
    def __init__(self, adb: Adb, serial: str, sleep=time.sleep, settle_s: float = 2.0, wait_s: float = 15.0,
                 reader=None):
        """`reader` (agent.screen_reader.U2Reader, see for_phone) reads the screens `uiautomator dump` cannot."""
        self.adb, self.serial, self.sleep, self.settle_s, self.wait_s = adb, serial, sleep, settle_s, wait_s
        self.reader, self.reader_on = reader, False

    @classmethod
    def for_phone(cls, adb: Adb, serial: str) -> TikTokUi:
        """The Agent's TikTokUi: with the second screen reader for screens that never stop moving."""
        from agent.screen_reader import U2Reader

        return cls(adb, serial, reader=U2Reader(adb, serial))

    def sh(self, command: str) -> str:
        return self.adb.shell(self.serial, command)

    # --- reading the screen ------------------------------------------------------------------

    def focus(self) -> str:
        m = re.search(r"mCurrentFocus=\S+ \S+ (\S+?)\}", self.sh("dumpsys window | grep mCurrentFocus"))
        return m.group(1) if m else ""

    def read(self, *, check: bool = True, exact: bool = False) -> list[Node]:
        """A fresh reading of the screen (the old dump is deleted first: it would be read otherwise).

        When `uiautomator dump` reads nothing (a screen that never stops moving), the second reader is
        used from then on: `uiautomator dump` takes ~12 s to give up each time (tx1, 2026-10-13) and cannot
        run beside it. The second reader shows emoji as "..", so `exact` (every caption check) stops it and
        reads with `uiautomator dump` only: a caption is never checked from the second reader."""
        nodes: list[Node] = []
        if exact and self.reader_on:
            self.reader.stop()
            self.reader_on = False
        if not self.reader_on:
            self.sh(f"rm -f {DUMP}")
            try:
                self.sh(f"uiautomator dump {DUMP} >/dev/null")
                nodes = parse_dump(self.sh(f"cat {DUMP}"))
            except AdbError:
                nodes = []
        if not nodes and not exact and self.reader is not None:
            from agent.screen_reader import ReaderError

            try:
                self.reader_on = True
                nodes = parse_dump(self.reader.dump())
            except (ReaderError, AdbError):
                nodes = []  # read as "nothing on screen": the callers look again or stop, never guess
        if check:
            stop = classify(nodes)
            if stop:
                raise UiStop(stop, "TikTok shows a login or verification screen; a person must handle it")
        return nodes

    def find(self, nodes: list[Node], *labels: str) -> Node | None:
        wanted = {lbl.lower() for lbl in labels}
        return next((n for n in nodes if n.label.lower() in wanted), None)

    def wait_for(self, *labels: str) -> Node:
        deadline = time.monotonic() + self.wait_s
        while True:
            node = self.find(self.read(), *labels)
            if node is not None:
                return node
            if time.monotonic() >= deadline:
                raise UiStop("UNKNOWN_SCREEN", f"expected one of {labels}; focus {self.focus()}")
            self.sleep(1.0)

    # --- acting --------------------------------------------------------------------------------

    def press(self, *labels: str) -> None:
        """Press the element with one of these labels, after checking what is under the point right now."""
        node = self.wait_for(*labels)
        x, y = node.center
        current = self.read()
        wanted = {lbl.lower() for lbl in labels}
        here = under(current, x, y)  # smallest first
        target = next((n for n in here if n.label.lower() in wanted), None)
        if target is None:
            raise UiStop("SCREEN_CHANGED", f"{labels[0]!r} is no longer at {x},{y}")
        # A forbidden control at the point blocks the press, unless it is a larger container that wholly
        # encloses the target (QA phone, 2026-10-11: after a post the feed's "LIVE" view spans the screen
        # behind the tab bar, and the Profile tab sits on top of it).
        blocking = [n for n in here if forbidden(n) and not (n.area > target.area and encloses(n, target))]
        if blocking or forbidden(node) or forbidden(target):
            raise UiStop("REFUSED_ELEMENT", f"refused to press at {x},{y}: a forbidden control is there")
        self.sh(f"input swipe {x} {y} {x} {y} 120")  # short press: plain taps fell through sheets (P1)
        self.sleep(self.settle_s)

    def keyboard_shown(self) -> bool:
        return "mInputShown=true" in self.sh("dumpsys input_method | grep mInputShown")

    def open_app(self) -> None:
        self.sh(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1")
        self.sleep(self.settle_s * 3)

    def account(self, tries: int = 6) -> str:
        """Open TikTok on Profile and read the @handle. TikTok can take a while to start or show a
        popup first, so it looks again a few times; it never guesses an account.

        QA phone, 2026-10-11 (TikTok 40.0.0): the For You feed runs inside SplashActivity, so that name
        says nothing about a splash screen (waiting on it cost ~20 s each time); and once TikTok was no
        longer in front (the last reading was the home screen), so TikTok is opened again whenever the
        screen is not TikTok's."""
        self.open_app()
        size = re.search(r"(\d+)x(\d+)", self.sh("wm size"))
        w, h = (int(size.group(1)), int(size.group(2))) if size else (720, 1600)
        covered = 0
        for _ in range(tries):
            if not self.focus().startswith(PACKAGE):  # TikTok closed or went behind another app
                self.open_app()
            nodes = self.read()
            handle = account_handle(nodes)
            if handle is not None:
                return handle
            if self.find(nodes, "กำลังติดตาม", "Following") and self.find(nodes, "ผู้ติดตาม", "Followers"):
                # Already on Profile, the @handle covered (tx1, 2026-10-13: the "continue editing your
                # unposted video?" banner, closed with ยกเลิก). Anything else is waited out once, then
                # Profile is pressed again as before 0.5.6 (tx2, 2026-10-13: right after a post the handle
                # stayed covered while only waiting, and the post became UNKNOWN). A shop card behind the
                # tab bar makes that press refused: then nothing is pressed and it waits again.
                covered += 1
                if self.dismiss_resume_banner():
                    continue
                if covered >= 2 and self.find(nodes, "โปรไฟล์", "Profile") is not None:
                    try:
                        self.press("โปรไฟล์", "Profile")
                        continue
                    except UiStop as exc:  # refused or moved: nothing was pressed
                        if exc.code not in ("SCREEN_CHANGED", "UNKNOWN_SCREEN", "REFUSED_ELEMENT"):
                            raise
                self.sleep(self.settle_s * 3)
                continue
            tab = self.find(nodes, "โปรไฟล์", "Profile")
            if tab is not None:
                try:
                    self.press("โปรไฟล์", "Profile")
                except UiStop as exc:  # the screen moved under us (popup, feed loading): look again
                    if exc.code not in ("SCREEN_CHANGED", "UNKNOWN_SCREEN"):
                        raise
                    self.sleep(self.settle_s)
            else:
                # The feed cannot be dumped while a video plays: press the bottom-right tab, then look again.
                x, y = int(w * 0.9), int(h * 0.91)
                self.sh(f"input swipe {x} {y} {x} {y} 120")
                self.sleep(self.settle_s * 2)
        self.sh("screencap -p /sdcard/cf_last.png")  # kept on the phone for diagnosis (removed by cleanup)
        raise UiStop("ACCOUNT_UNREADABLE", f"could not read the logged-in account on Profile; focus {self.focus()}")

    def dismiss_resume_banner(self) -> bool:
        """Press ยกเลิก on TikTok's "continue editing your unposted video?" banner (PO 2026-10-13), and
        nothing else: the button must sit inside the small banner that carries exactly that question, and
        nothing else of the banner may be under the point. Returns False when there is no such banner."""
        if self.reader is None:
            return False
        from agent.screen_reader import ReaderError

        def banner(nodes: list[Node]) -> tuple[Node, Node] | None:
            question = next((n for n in nodes if n.label in RESUME_BANNER), None)
            if question is None:
                return None
            boxes = [n for n in nodes if not n.label and encloses(n, question) and n.area < question.area * 6]
            for box in sorted(boxes, key=lambda n: n.area):
                buttons = [n for n in nodes if n.label in RESUME_CANCEL and n.clickable and encloses(box, n)]
                if len(buttons) == 1:
                    return box, buttons[0]
            return None

        try:
            self.reader_on = True
            nodes = parse_dump(self.reader.dump(all_windows=True))
        except (ReaderError, AdbError):
            return False
        found = banner(nodes)
        if found is None:
            return False
        box, cancel = found
        x, y = cancel.center
        inside = [n for n in under(nodes, x, y) if encloses(box, n)]
        if any(n.label and n.label not in RESUME_CANCEL for n in inside) or any(forbidden(n) for n in inside):
            raise UiStop("REFUSED_ELEMENT", f"refused to press at {x},{y}: not only ยกเลิก on the banner")
        self.sh(f"input swipe {x} {y} {x} {y} 120")
        self.sleep(self.settle_s)
        try:
            still = banner(parse_dump(self.reader.dump(all_windows=True)))
        except (ReaderError, AdbError):
            still = None
        if still is not None:
            raise UiStop("RESUME_BANNER", "TikTok's 'continue editing?' banner stayed after ยกเลิก")
        return True

    def check_account(self, expected: str) -> str:
        handle = self.account()
        if handle != expected.lower().lstrip("@"):
            raise UiStop("ACCOUNT_MISMATCH", f"phone is logged in as @{handle}, expected @{expected.lstrip('@')}")
        return handle

    def open_post_screen(self, media_id: str) -> None:
        """Share the exact file into TikTok and get to the post screen (never Story)."""
        self.sh("am start -a android.intent.action.SEND -t video/mp4 "
                f"--eu android.intent.extra.STREAM content://media/external/video/media/{media_id} -f 1 -n {SHARE_ACTIVITY}")
        self.sleep(self.settle_s * 2)
        self.press("วิดีโอ", "Video")
        self.press("ถัดไป", "Next")
        nodes = self.read()
        if visibility_row(nodes) is None or not any(n.cls.endswith("EditText") for n in nodes):
            raise UiStop("UNKNOWN_SCREEN", f"not the post screen; focus {self.focus()}")

    def set_only_me(self) -> None:
        row = visibility_row(self.read())
        if row is None:
            raise UiStop("UNKNOWN_SCREEN", "visibility row not found on the post screen")
        if any(m in row.label.lower() for m in ONLY_ME):
            return
        self.press(row.label)
        self.press("เฉพาะคุณเท่านั้น", "Only you", "Only me")
        nodes = self.read()
        if self.find(nodes, "ปิด", "Close") is not None and visibility_row(nodes) is None:
            self.press("ปิด", "Close")  # the sheet did not close by itself
            nodes = self.read()
        row = visibility_row(nodes)
        if row is None or not any(m in row.label.lower() for m in ONLY_ME):
            raise UiStop("VISIBILITY_NOT_SET", "visibility did not change to only you")

    def type_caption(self, caption: str) -> None:
        field = next((n for n in self.read() if n.cls.endswith("EditText")), None)
        if field is None:
            raise UiStop("UNKNOWN_SCREEN", "caption field not found")
        x, y = field.center
        self.sh(f"input swipe {x} {y} {x} {y} 120")
        self.sleep(self.settle_s)
        keyboard = thai_keyboard.ime(self.adb, self.serial)
        if keyboard is None:
            raise UiStop("THAI_KEYBOARD_MISSING", "no Thai keyboard (punpun Thai input) on this phone")
        original = self.sh("settings get secure default_input_method").strip()
        msg = base64.b64encode(caption.encode("utf-8")).decode()
        on_screen = None
        try:
            self.sh(f"ime enable {keyboard}")  # available, not the default (a no-op when it already is)
            self.sh(f"ime set {keyboard}")
            # QA phone, 2026-10-12: one caption came out wrong on the first post after a restart. Typing
            # right after `ime set` can reach the keyboard before it listens, so it gets a moment, and a
            # wrong result is cleared and typed once more (all before Post; the check below still decides).
            self.sleep(self.settle_s)
            for _ in range(2):
                self.sh("am broadcast -a ADB_CLEAR_TEXT")
                self.sh(f"am broadcast -a ADB_INPUT_B64 --es msg {msg}")
                self.sleep(self.settle_s)
                typed = next((n for n in self.read(exact=True) if n.cls.endswith("EditText")), None)
                on_screen = typed.text if typed is not None else None
                if on_screen is not None and on_screen.strip() == caption.strip():
                    break
        finally:
            if original and original != keyboard:
                self.sh(f"ime set {original}")  # the owner's keyboard comes back every time
        typed = next((n for n in self.read(exact=True) if n.cls.endswith("EditText")), None)
        if typed is None or typed.text.strip() != caption.strip():
            seen = typed.text if typed is not None else on_screen
            raise UiStop("CAPTION_MISMATCH", f"the caption on screen is not the approved text: {len(caption.strip())} "
                                             f"characters approved, screen shows {seen[:120]!r}" if seen is not None
                         else "the caption on screen is not the approved text: no caption field")
        if self.keyboard_shown():
            self.sh("input keyevent KEYCODE_BACK")  # only closes the keyboard: checked above
            self.sleep(self.settle_s)

    # --- the authorized post (Q-29) and its verification ---------------------------------------

    def private_count(self, tries: int = 6) -> int:
        """Private videos on Profile (lock tiles), read on the private tab. The grid loads late (QA phone:
        0 on the first reading, 1 on the next), so the count is taken only when two readings agree."""
        self.press("วิดีโอส่วนตัว", "Private videos", "Private")
        last = None
        for _ in range(tries):
            self.sleep(self.settle_s)
            count = sum(1 for n in self.read() if n.desc in ("ล็อก", "Private") and n.bounds[1] > 850)
            if count == last:
                return count
            last = count
        raise UiStop("PRIVATE_COUNT_UNSTABLE", "the private videos grid did not settle")

    def submit(self, grant, caption: str) -> None:
        """Press Post once. Only with a grant from agent.authorization (used and recorded beforehand),
        and only on a post screen whose caption, visibility and button position are what we expect."""
        from agent.authorization import PostGrant

        if not isinstance(grant, PostGrant):
            raise UiStop("NO_GRANT", "posting needs a recorded one-time grant")
        if self.keyboard_shown():
            raise UiStop("KEYBOARD_SHOWN", "the keyboard is up; Post would be at another place")
        nodes = self.read(exact=True)
        field = next((n for n in nodes if n.cls.endswith("EditText")), None)
        row = visibility_row(nodes)
        if field is None or field.text.strip() != caption.strip():
            raise UiStop("CAPTION_MISMATCH", "caption changed before Post")
        if row is None or not any(m in row.label.lower() for m in ONLY_ME):
            raise UiStop("VISIBILITY_NOT_SET", "visibility is not only you")
        buttons = [n for n in nodes if n.label in ("โพสต์", "Post") and n.clickable and n.bounds[1] > 1300]
        if len(buttons) != 1:
            raise UiStop("UNKNOWN_SCREEN", "the Post button is not where it belongs")
        x, y = buttons[0].center
        if any(n.label not in ("โพสต์", "Post") for n in under(nodes, x, y)):
            raise UiStop("SCREEN_CHANGED", "something else is under the Post button")
        self.sh(f"input swipe {x} {y} {x} {y} 120")

    def verify_private_post(self, marker: str, before: int, tries: int = 4, wait_s: float = 20.0) -> dict:
        """PRD §H: the post is on this account's private tab and its caption carries the attempt marker.

        The marker (unique per post) is the proof. The tile count is not: Profile shows only the tiles
        that fit above the tab bar (QA phone, 2026-10-11: 5, so a 6th post read 5 -> 5 and a published
        post became UNKNOWN). A count that went down still stops. While TikTok is still uploading, the
        newest tile is the previous post, so it looks again a few times (Back to Profile, never a
        force-stop, which would end the upload)."""
        for attempt in range(tries):
            if attempt:
                self.sh("input keyevent KEYCODE_BACK")  # from the opened video back to Profile
                self.sleep(wait_s)
            try:
                return self._newest_private_has(marker, before)
            except UiStop as exc:
                # ACCOUNT_UNREADABLE too (tx2, 2026-10-13: right after Post, b7f207dd became UNKNOWN on the
                # first reading of Profile): reading again a little later decides, never a guess.
                if exc.code not in ("VERIFY_MARKER", "VERIFY_UNREADABLE", "ACCOUNT_UNREADABLE") or attempt == tries - 1:
                    raise
        raise AssertionError("unreachable")

    def _newest_private_has(self, marker: str, before: int) -> dict:
        handle = self.account()
        after = self.private_count()
        if after < before:
            raise UiStop("VERIFY_COUNT", f"private videos {before} -> {after}, fewer than before")
        locks = sorted((n for n in self.read() if n.desc == "ล็อก" and n.bounds[1] > 850),
                       key=lambda n: (n.bounds[1], n.bounds[0]))
        if not locks:
            raise UiStop("VERIFY_MARKER", "no private video on Profile yet")
        x, y = locks[0].center
        self.sh(f"input swipe {x} {y - 60} {x} {y - 60} 120")  # newest tile (the lock icon sits on it)
        self.sleep(self.settle_s * 2)
        self.sh("input tap 360 650")  # pause: a playing video cannot be read
        self.sleep(self.settle_s)
        nodes = self.read()
        caption = next((n for n in nodes if "ส่วนตัว" in n.text or "private" in n.text.lower()), None)
        if caption is None:
            raise UiStop("VERIFY_UNREADABLE", "caption of the newest private video not found")
        cx, cy = caption.center
        self.sh(f"input swipe {cx} {cy} {cx} {cy} 120")  # expand: the marker is at the end
        self.sleep(self.settle_s)
        texts = " ".join(n.text for n in self.read())
        if marker not in texts:
            raise UiStop("VERIFY_MARKER", "the newest private video does not carry this attempt's marker")
        return {"method": "caption_marker", "value": marker, "account": handle,
                "private_before": before, "private_after": after}

    def screenshot(self, remote: str = "/sdcard/cf_check.png") -> str:
        self.sh(f"screencap -p {remote}")
        return remote

    def close(self) -> None:
        """Leave without posting or keeping anything."""
        self.sh(f"am force-stop {PACKAGE}")
        if self.reader is not None and self.reader_on:
            self.reader.stop()
            self.reader_on = False


def media_id(adb: Adb, serial: str, name: str) -> str | None:
    rows = adb.shell(serial, "content query --uri content://media/external/video/media --projection _id:_display_name")
    for line in rows.splitlines():
        m = re.search(r"_id=(\d+), _display_name=(.+)$", line.strip())
        if m and m.group(2).strip() == name:
            return m.group(1)
    return None
