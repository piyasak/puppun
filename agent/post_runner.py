"""Agent post runner (P5.2/P5.3, E-42): take a due post from the server and carry it out on the phone.

    every POLL_S while idle (E-41): find ready phones (ro.serialno) -> claim
    TRANSFERRING: get the bound file (own render if the hash matches, else download + verify)
                  -> push to a hidden staging name, verify SHA-256 on the phone, rename into place
    PREPARING:    ask the media scanner, wait until the Gallery (MediaStore) lists the file
    dry-run:      stop here (DRY_RUN_DONE) and remove the test file from the phone

Every step is written to the local attempt journal *before* it runs (attempt.py) and reported
to the server with an Agent event id (retried with the same id, deduplicated there).
LEASE_LOST / ITEM_NOT_ACTIVE / a lost session stop the post: nothing more is done for it.
Failures before Submit are reported as RETRYABLE_FAILED; the server decides about redelivery.

Delete after post (PO 2026-10-10): every FREE_SPACE_EVERY_S the runner asks which kept clips the
server says may go (their job deletes clips once posted, a post of the clip is verified and no other
post of it is pending or UNKNOWN), deletes each file for good when its SHA-256 still matches, and
reports it. A file that changed is left alone and reported nowhere.

Live posts (Q-42): the server hands a post out live only under an admin's posting grant for the
phone's account. The Agent then checks the account on screen, sets "only you", types the exact
caption plus the attempt marker, reports SUBMITTING (the server counts the grant use there, under a
lock, or refuses) and only then presses Post once; it verifies by the marker, and anything unsure
after Post is UNKNOWN, never retried. A post without a grant, or with a visibility this Agent cannot
set, is never pressed. The local one-time ledger (agent.authorization) remains only for the opt-in
real-phone test.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import random
import re
import threading
import time
import uuid
from pathlib import Path

from agent import account_stats, diagnostics, marker, thai_keyboard, ui_profile
from agent.adb import Adb, AdbError, normalize_serial
from agent.attempt import PRE_SUBMIT, AttemptJournal, State, TransitionError
from agent.authorization import GrantRefused, PostGrant
from agent.compat import check_phone
from agent.device_registry import discover
from agent.server_client import ServerClient, ServerError
from agent.tiktok_ui import TikTokUi, UiStop, media_id

STOP_CODES = {"LEASE_LOST", "ITEM_NOT_ACTIVE", "AGENT_SESSION_ENDED"}
FREE_SPACE_EVERY_S = 300.0
PROFILE_EVERY_S = 3600.0  # Q-50: the UI profile is fetched on start and hourly
STAGGER_S = (30.0, 90.0)  # PO 2026-10-23: same-time posts on several phones start this far apart (random)


# Q-49 (PO 2026-10-15): "everyone" = public; verified on Profile's videos grid (TikTokUi.verify_public_post).
SUPPORTED_VISIBILITY = ("only_me", "everyone")
# "<post id>-<server attempt>" with an optional ".r<k>" when that number came back after a retry
ATTEMPT_ID_RE = re.compile(r"^(?P<post>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-(?P<n>\d+)(?:\.r\d+)?$")
LINK_RE = re.compile(r"(https?://|www\.|\b[a-z0-9-]+\.(?:com|net|org|co|th|io|me|ly|gl|link|shop|app|xyz|info|biz|tv|cc|to)\b)",
                     re.IGNORECASE)

class PostStopped(Exception):
    """The server says this Agent no longer holds the post."""


class PostFailed(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class PostRunner:
    def __init__(self, data_dir: Path, adb_factory, log=print, poll_s: float = 15.0, cleanup: bool = True,
                 retries: int = 3, retry_wait_s: float = 2.0, ui_rehearsal: bool = False, ui_factory=None,
                 grant_source=None, crash_after_submit: bool = False, screens=None, max_parallel: int = 1,
                 stagger_s: tuple[float, float] = STAGGER_S, rng: random.Random | None = None, push_slots: int = 2):
        self.data_dir, self.adb_factory, self.log = Path(data_dir), adb_factory, log
        self.poll_s, self.cleanup = poll_s, cleanup
        # Q-27: in dry runs, also go through TikTok up to (never including) Post, then close it.
        self.ui_rehearsal = ui_rehearsal
        self.ui_factory = ui_factory
        # Q-29: a live post needs a one-time grant (agent.authorization.take) handed in explicitly.
        self.grant_source = grant_source
        self.screens = screens  # phone screen windows: view-only on a phone while a post runs on it
        self.crash_after_submit = crash_after_submit  # fault injection for G5-04: stop dead after Post
        self.retries, self.retry_wait_s = retries, retry_wait_s
        self.journal = AttemptJournal(self.data_dir / "attempts.jsonl")
        self.profile = ui_profile.load_cached(self.data_dir)  # Q-50: last good one, else built in
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        # 0.10.0 (PO 2026-10-23): up to `max_parallel` phones work at once (default 1 = one at a time as
        # before). A phone does one thing at a time; a post started while another runs waits a random
        # `stagger_s` first; clip pushes share `push_slots` (USB); each line of the log says which phone.
        self.max_parallel = max(1, int(max_parallel))
        self.stagger_s, self.rng = stagger_s, rng or random.Random()
        self.push_slots = threading.Semaphore(max(1, push_slots))
        self._active: dict[str, threading.Thread] = {}  # normalized hw serial -> the thread working on it
        self._active_lock = threading.Lock()
        self._next_start = 0.0
        self._tls = threading.local()
        self._raw_log = log
        self.log = self._log

    def _log(self, message: str) -> None:
        name = getattr(self._tls, "phone", None)
        self._raw_log(f"[{name}] {message}" if name and self.max_parallel > 1 else message)

    # --- background loop -------------------------------------------------------------------

    def settle_journal(self, client: ServerClient, get_session) -> list[str]:
        """On start: records this PC left between Submit and a result (Agent closed or updated mid-post) are
        settled when the server no longer waits for that attempt (2026-10-15, 5b3b367d-…-1: resolved by a
        person on the web, still SUBMITTING here, and every update was refused). Records the server still
        waits for stay as they are. Records stopped before Submit become RETRYABLE_FAILED (nothing posted)."""
        settled = []
        for attempt_id in self.journal.ids():
            current = self.journal.current(attempt_id)
            if current in PRE_SUBMIT:
                self.journal.recover(attempt_id)
                continue
            if current not in (State.SUBMITTING, State.VERIFYING):
                continue
            m = ATTEMPT_ID_RE.match(attempt_id)
            if m is None:
                continue
            try:
                server = client.post_state(get_session(), m["post"])
            except ServerError as exc:
                if exc.code != "NOT_FOUND":
                    continue  # try again on the next start
                server = {"state": "NOT_FOUND", "attempt": None}
            if server["state"] in ("SUBMITTING", "VERIFYING") and server.get("attempt") == int(m["n"]):
                continue  # the server still waits for this very attempt
            self.journal.settle(attempt_id, f"settled: server says {server['state']} (attempt {server.get('attempt')})")
            settled.append(attempt_id)
        if settled:
            self.log(f"บันทึกโพสต์ค้าง {len(settled)} รายการ: เซิร์ฟเวอร์มีผลแล้ว ปิดรายการในเครื่องนี้")
        return settled

    def refresh_profile(self, client: ServerClient, get_session) -> None:
        """Q-50: the server's latest UI profile, if it validates here too; otherwise the one in use stays."""
        try:
            answer = client.ui_profile(get_session())
        except (ServerError, OSError) as exc:
            self.log(f"ค่าหน้าจอ TikTok: โหลดจากเซิร์ฟเวอร์ไม่ได้ ({exc}); ใช้ชุดเดิม (เวอร์ชัน {self.profile.version})")
            return
        if answer is None or answer.get("version") == self.profile.version:
            return
        try:
            profile = ui_profile.from_server(answer)
        except ui_profile.ProfileError as exc:
            self.log(f"ค่าหน้าจอ TikTok เวอร์ชัน {answer.get('version')} ใช้ไม่ได้ ({exc}); ใช้ชุดเดิม")
            return
        ui_profile.save_cached(self.data_dir, answer)
        self.profile = profile
        self.log(f"ค่าหน้าจอ TikTok: ใช้เวอร์ชัน {profile.version}")

    def start(self, client: ServerClient, get_session) -> None:
        self._thread = threading.Thread(target=self._loop, args=(client, get_session), daemon=True,
                                        name="clipflow-posts")
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout_s)
        with self._active_lock:
            workers = list(self._active.values())
        for t in workers:
            t.join(timeout_s)

    # --- several phones at once (0.10.0) ---------------------------------------------------

    def active(self) -> set[str]:
        """Phones (normalized hw serial) something is running on now; finished ones are dropped."""
        with self._active_lock:
            for key in [k for k, t in self._active.items() if not t.is_alive()]:
                del self._active[key]
            return set(self._active)

    def _spawn(self, key: str, name: str, work) -> threading.Thread:
        def run() -> None:
            self._tls.phone = name
            try:
                work()
            except Exception as exc:  # noqa: BLE001 - one phone must never stop the others
                self.log(f"ข้อผิดพลาดที่ไม่คาดไว้ ({type(exc).__name__}: {exc}); เครื่องอื่นทำงานต่อ")
            finally:
                with self._active_lock:
                    if self._active.get(key) is threading.current_thread():
                        del self._active[key]

        thread = threading.Thread(target=run, daemon=True, name=f"clipflow-post-{name}")
        with self._active_lock:
            self._active[key] = thread
        thread.start()
        return thread

    def dispatch_once(self, client: ServerClient, get_session) -> bool:
        """Start one thing on a free phone (a due post first; else a screen check or Profile numbers).
        True when something was started."""
        busy = self.active()
        if len(busy) >= self.max_parallel:
            return False
        if busy and time.monotonic() < self._next_start:
            return False  # PO 2026-10-23: a post that starts while another runs waits a random 30-90 s
        adb = self.adb_factory()
        free = {key: p for key, p in self._ready_phones(adb).items() if key not in busy}
        if not free:
            return False
        post = client.claim_post(get_session(), [p.hw_serial for p in free.values()])
        if post is not None:
            key = normalize_serial(post["device"]["serial"])
            phone = free.get(key)
            self._next_start = time.monotonic() + self.rng.uniform(*self.stagger_s)
            self._spawn(key, self._name(post, phone), lambda: self._execute(client, get_session, post, adb, phone))
            return True
        request = client.diagnostic_requested(get_session(), [p.hw_serial for p in free.values()])
        if request is not None:
            key = normalize_serial(request["serial"])
            phone = free.get(key)
            if phone is None:
                client.diagnostic_done(get_session(), request["id"], error="PHONE_NOT_CONNECTED")
                return True
            self._spawn(key, phone.hw_serial, lambda: self._diagnose(client, get_session, adb, phone, request))
            return True
        clock = account_stats.StatsClock(self.data_dir / "stats_clock.json")
        for key, phone in free.items():
            if clock.due(phone.hw_serial):
                clock.mark(phone.hw_serial)  # once per period, even when the reading fails
                self._spawn(key, phone.hw_serial, lambda p=phone: self._read_stats(client, get_session, adb, p))
                return True
        return False

    @staticmethod
    def _name(post: dict, phone) -> str:
        device = post.get("device") or {}
        return device.get("display_name") or device.get("expected_account") or (phone.hw_serial if phone else "?")

    @staticmethod
    def _ready_phones(adb) -> dict:
        return {normalize_serial(p.hw_serial): p for p in discover(adb) if p.state == "device" and p.hw_serial}

    def _loop(self, client: ServerClient, get_session) -> None:
        try:
            self.settle_journal(client, get_session)
        except Exception as exc:  # noqa: BLE001 - a journal check must never keep posting from starting
            self.log(f"ตรวจบันทึกโพสต์ค้าง: ทำไม่ได้ ({type(exc).__name__}: {exc}); โพสต์ต่อ")
        next_free = next_profile = 0.0
        while not self._halt.is_set():
            if time.monotonic() >= next_profile:
                next_profile = time.monotonic() + PROFILE_EVERY_S
                try:
                    self.refresh_profile(client, get_session)
                except Exception as exc:  # noqa: BLE001 - the profile must never keep posting from running
                    self.log(f"ค่าหน้าจอ TikTok: ตรวจไม่ได้ ({type(exc).__name__}); ใช้ชุดเดิม")
            if time.monotonic() >= next_free:
                next_free = time.monotonic() + FREE_SPACE_EVERY_S
                try:
                    self.delete_posted_clips(client, get_session)
                except (ServerError, OSError) as exc:
                    self.log(f"ลบคลิปหลังโพสต์: ทำต่อไม่ได้ชั่วคราว ({exc}); ลองใหม่ภายหลัง")
            try:
                started = self.dispatch_once(client, get_session)
            except (ServerError, OSError, AdbError) as exc:
                self.log(f"โพสต์: ทำต่อไม่ได้ชั่วคราว ({exc}); ลองใหม่ภายหลัง")
                started = False
            except Exception as exc:  # noqa: BLE001 - never let one post stop posting for every phone
                self.log(f"โพสต์: ข้อผิดพลาดที่ไม่คาดไว้ ({type(exc).__name__}: {exc}); ทำงานต่อ")
                started = False
            # Started: look again at once (another phone may be due); otherwise E-41 (<= 15 s), or sooner
            # while phones are busy so a finished phone is picked up quickly.
            if not started:
                self._halt.wait(self.poll_s if not self.active() else min(self.poll_s, 5.0))

    def delete_posted_clips(self, client: ServerClient, get_session) -> list[str]:
        """Delete (for good) the kept clips the server lists as posted and done. Returns the clip ids reported."""
        from agent import clips_folder

        session = get_session()
        reported = []
        for item in client.deletable_clips(session):
            name = f"clip_{item['index']:02d}"
            homes = [f / item["job_id"] for f in clips_folder.search_order(self.data_dir)]
            video = next((h / f"{name}.mp4" for h in homes if (h / f"{name}.mp4").is_file()), None)
            if video is not None and sha256_file(video) != item["sha256"]:
                self.log(f"ลบคลิปหลังโพสต์: ข้าม {video} เพราะไฟล์ไม่ตรงกับที่โพสต์ (ไม่ลบ)")
                continue
            freed = 0
            if video is not None:
                freed = video.stat().st_size
                video.unlink()
                still = video.with_suffix(".jpg")
                if still.is_file():
                    freed += still.stat().st_size
                    still.unlink()
                with contextlib.suppress(OSError):
                    video.parent.rmdir()  # only when nothing else is left in the job folder
                self.log(f"ลบคลิปหลังโพสต์: {video} (ได้พื้นที่คืน {freed / 1024**2:.0f} MB)")
            client.clip_file_deleted(session, item["clip_id"], found=video is not None)
            reported.append(item["clip_id"])
        return reported

    def run_diagnostic_once(self, client: ServerClient, get_session) -> bool:
        """A screen check asked for on the web (PO 2026-10-16), when no post is running. True if one ran."""
        adb = self.adb_factory()
        phones = {normalize_serial(p.hw_serial): p for p in discover(adb) if p.state == "device" and p.hw_serial}
        if not phones:
            return False
        request = client.diagnostic_requested(get_session(), [p.hw_serial for p in phones.values()])
        if request is None:
            return False
        phone = phones.get(normalize_serial(request["serial"]))
        if phone is None:
            client.diagnostic_done(get_session(), request["id"], error="PHONE_NOT_CONNECTED")
            return True
        self._diagnose(client, get_session, adb, phone, request)
        return True

    def _diagnose(self, client, get_session, adb, phone, request) -> None:
        lock = self.screens.locked(phone.adb_serial) if self.screens else contextlib.nullcontext()
        with lock:
            diagnostics.run_requested(client, get_session(), adb, phone.adb_serial, request, self.profile, self.log,
                                      self.ui_factory)

    def _read_stats(self, client, get_session, adb, phone) -> None:
        lock = self.screens.locked(phone.adb_serial) if self.screens else contextlib.nullcontext()
        with lock:
            ui = (self.ui_factory or (lambda a, s: TikTokUi.for_phone(a, s, self.profile)))(adb, phone.adb_serial)
            account_stats.read_and_send(client, get_session(), ui, phone.hw_serial, self.log)

    def read_stats_once(self, client: ServerClient, get_session) -> bool:
        """Q-52: when idle, read one phone's Profile numbers if its last reading is old enough."""
        adb = self.adb_factory()
        clock = account_stats.StatsClock(self.data_dir / "stats_clock.json")
        for phone in discover(adb):
            if phone.state != "device" or not phone.hw_serial or not clock.due(phone.hw_serial):
                continue
            clock.mark(phone.hw_serial)  # once per period, even when the reading fails
            self._read_stats(client, get_session, adb, phone)
            return True
        return False

    def run_once(self, client: ServerClient, get_session) -> str | None:
        """Claim and carry out one post. Returns its final state, "stopped", or None if nothing was due."""
        adb = self.adb_factory()
        phones = {normalize_serial(p.hw_serial): p for p in discover(adb) if p.state == "device" and p.hw_serial}
        if not phones:
            return None
        post = client.claim_post(get_session(), [p.hw_serial for p in phones.values()])
        if post is None:
            return None
        return self._execute(client, get_session, post, adb, phones.get(normalize_serial(post["device"]["serial"])))

    def _execute(self, client, get_session, post: dict, adb, phone) -> str:
        lock = self.screens.locked(phone.adb_serial) if self.screens and phone else contextlib.nullcontext()
        with lock:  # a click on the PC must never meet the Agent's taps on the same phone
            return _Post(self, client, get_session, post, adb, phone).run()


class _Post:
    def __init__(self, runner: PostRunner, client: ServerClient, get_session, post: dict, adb: Adb, phone):
        self.r, self.client, self.get_session, self.post = runner, client, get_session, post
        self.adb, self.phone = adb, phone
        self.id = post["id"]
        self.attempt_id = self._new_attempt_id(f"{self.id}-{post['attempt']}")
        self.state = post["state"]
        self.remote: str | None = None

    def _new_attempt_id(self, base: str) -> str:
        """The server's attempt number starts again at 1 after a person presses retry (posts.retry), so this
        PC's journal may already hold that id (PC of tx1/tx2, 2026-10-15: f240f595-…-1 came back after a
        retry and stopped the posting thread). A taken id gets a suffix; the old attempt's record stays."""
        attempt_id, n = base, 1
        while self.r.journal.current(attempt_id) is not None:
            n += 1
            attempt_id = f"{base}.r{n}"
        return attempt_id

    def event(self, kind: str, **payload) -> None:
        body = {"event_id": uuid.uuid4().hex, "type": kind, **payload}
        for attempt in range(self.r.retries):
            try:
                self.state = self.client.post_event(self.get_session(), self.id, body)["state"]
                return
            except ServerError as exc:
                if exc.code in STOP_CODES:
                    raise PostStopped(exc.code) from None
                raise
            except OSError:
                if attempt + 1 == self.r.retries:
                    raise
                self.r._halt.wait(self.r.retry_wait_s * (attempt + 1))

    def step(self, state: State, kind: str | None = None, detail: str = "") -> None:
        """Journal first (write-ahead), then tell the server."""
        self.r.journal.advance(self.attempt_id, state, detail)
        if kind:
            self.event(kind)

    def run(self) -> str:
        tag = f"โพสต์ {self.id[:8]}"
        self.r.journal.begin(self.attempt_id)
        try:
            if self.phone is None:
                raise PostFailed("DEVICE_NOT_CONNECTED", "phone is no longer connected to this PC")
            self.step(State.TRANSFERRING, "TRANSFERRING")
            local = self._file()
            name = f"cf_{self.id[:8]}_{self.post['clip']['index']:02d}.mp4"
            try:
                with self.r.push_slots:  # several phones at once share the USB (0.10.0)
                    self.remote = self.adb.push_verified(self.phone.adb_serial, local, remote_name=name)
            except AdbError as exc:
                raise PostFailed("TRANSFER_FAILED", str(exc)[:200]) from None
            self.step(State.PREPARING, "PREPARING", self.remote)
            if not self.adb.scan_and_find(self.phone.adb_serial, self.remote):
                raise PostFailed("GALLERY_NOT_FOUND", "the phone's Gallery did not list the clip")
            if self.post["posting_mode"] == "live" or self.r.ui_rehearsal:
                self._check_compat()
            if self.post["posting_mode"] == "live":
                if self._live():
                    return "crashed"  # simulated process death: nothing else happens (G5-04)
            else:
                if self.r.ui_rehearsal:
                    self._rehearse()
                self.r.journal.advance(self.attempt_id, State.CANCELLED, "dry-run: stopped before submit")
                self.event("DRY_RUN_DONE")
                self.r.log(f"{tag}: ทดสอบสำเร็จ — ไฟล์อยู่ในโทรศัพท์และ Gallery แล้ว หยุดก่อนกดโพสต์ (dry-run)")
        except PostStopped as exc:
            with contextlib.suppress(TransitionError):
                self.r.journal.advance(self.attempt_id, State.CANCELLED, f"server: {exc}")
            self.r.log(f"{tag}: หยุดตามที่ Server แจ้ง ({exc})")
            self._cleanup()
            return "stopped"
        except PostFailed as exc:
            self._fail(exc.code, exc.detail)
        except UiStop as exc:  # login wall, CAPTCHA, wrong account, unknown screen: a person decides
            self._needs_action(exc.code, exc.detail)
        except (ServerError, OSError, AdbError) as exc:
            self._fail("AGENT_ERROR", type(exc).__name__)
        self._cleanup()
        self.r.log(f"{tag}: {self.state}")
        return self.state

    def _rehearse(self) -> None:
        """Account check + visibility + exact caption in TikTok, then close without posting."""
        ui = self._ui()
        caption = self._caption()
        try:
            ui.check_account(self.post["device"]["expected_account"])
            found = media_id(self.adb, self.phone.adb_serial, self.remote.rsplit("/", 1)[-1])
            if found is None:
                raise PostFailed("GALLERY_NOT_FOUND", "no MediaStore id for the clip")
            ui.open_post_screen(found)
            ui.set_only_me()
            ui.type_caption(caption)
            self.r.log(f"โพสต์ {self.id[:8]}: ซ้อมใน TikTok ผ่าน — บัญชีตรง ข้อความตรง หยุดก่อนกดโพสต์")
        except UiStop as exc:
            self._capture(ui, exc.code)
            raise
        finally:
            ui.close()

    def _check_compat(self) -> None:
        """Never drive TikTok on a phone/app combination that was not tested (D03, NF-10, T25)."""
        report = self.adb.doctor(self.phone.adb_serial)
        verdict = check_phone(report.model, report.android_release, report.tiktok_package, report.tiktok_version)
        if not verdict.supported:
            raise UiStop("UNSUPPORTED_DEVICE", verdict.reason)

    def _capture(self, ui, code: str) -> None:
        """PO 2026-10-16: the screen when a post stopped on TikTok, for the web (never raises)."""
        diagnostics.capture_failure(self.client, self.get_session(), ui, self.post["device"]["serial"], self.id,
                                    code, self.r.log)

    def _ui(self):
        if self.r.ui_factory:
            ui = self.r.ui_factory(self.adb, self.phone.adb_serial)
        else:
            ui = TikTokUi.for_phone(self.adb, self.phone.adb_serial, self.r.profile)
        ui.account_check = self.post["device"].get("account_check", True) is not False  # Q-48; older servers: on
        return ui

    def _caption(self, marker: str | None = None) -> str:
        """The approved text and hashtags, then a space and the attempt's invisible marker (Q-49: no visible
        digits). The space ends the last hashtag: glued to it, TikTok kept the hashtag suggestion list open
        over Post (PC of tx1/tx2, 2026-10-15)."""
        text = self.post["text"]
        parts = [text["caption"], *[t for t in text["hashtags"] if t not in text["caption"]]]
        return " ".join(parts).strip() + (" " + marker if marker else "")

    def _live(self) -> bool:
        """An authorized post (Q-42 server grant, or the Q-29 local ledger in the opt-in test).
        Returns True when a crash after Post was simulated."""
        server_grant = self.post.get("grant")
        if self.r.grant_source is None and not server_grant:
            raise PostFailed("POSTING_NOT_AVAILABLE", "no posting grant for this post")
        visibility = (server_grant or {}).get("visibility", "only_me")
        if visibility not in SUPPORTED_VISIBILITY:
            raise PostFailed("VISIBILITY_NOT_SUPPORTED", f"this Agent cannot post as {visibility!r}")
        if LINK_RE.search(self.post["text"]["caption"] or ""):  # Q-49: approved before links were refused
            raise PostFailed("CAPTION_HAS_LINK", "the caption has a link (against TikTok's rules)")
        if not thai_keyboard.installed(self.adb, self.phone.adb_serial):  # before anything is typed or used
            raise UiStop("THAI_KEYBOARD_MISSING", "no Thai keyboard (punpun Thai input) on this phone")
        ui = self._ui()
        mark = marker.hidden(self.id)  # ties the post to this attempt (PRD §H, Q-21), invisible (Q-49)
        caption = self._caption(mark)
        crashed = False
        try:
            ui.check_account(self.post["device"]["expected_account"])
            before = ui.private_count() if visibility == "only_me" else None
            found = media_id(self.adb, self.phone.adb_serial, self.remote.rsplit("/", 1)[-1])
            if found is None:
                raise PostFailed("GALLERY_NOT_FOUND", "no MediaStore id for the clip")
            ui.open_post_screen(found)
            ui.set_visibility(visibility)
            ui.type_caption(caption)
            ui.ready_to_post(caption, visibility)  # before SUBMITTING: a covered Post stops here, nothing used
            # The session must be alive before a grant is spent: a grant used and then refused by the server
            # is lost (QA run 2026-10-08: the session expired during the TikTok steps).
            try:
                self.client.heartbeat(self.get_session())
            except ServerError as exc:
                if exc.code in STOP_CODES:
                    raise PostStopped(exc.code) from None
                raise
            if self.r.grant_source is not None:
                try:  # used and fsynced first: an exhausted grant stops here, before the server hears SUBMITTING
                    grant = self.r.grant_source(f"post {self.id}")
                except GrantRefused as exc:
                    raise PostFailed("NO_GRANT", str(exc)) from None
            # The server checks approval again (PRD §G.6) and counts the grant use; a refusal stops here.
            self.event("SUBMITTING")
            if self.r.grant_source is None:
                grant = PostGrant(f"server:{server_grant['id']}", 0)
            self.r.journal.advance(self.attempt_id, State.SUBMITTING, f"grant {grant.decision} #{grant.number}")
            try:
                ui.submit(grant, caption, visibility)
            except UiStop as exc:  # after SUBMITTING the server accepts only UNKNOWN; Post was not pressed
                self._capture(ui, exc.code)
                detail = f"stopped before pressing Post: {exc.detail}"
                self.r.journal.advance(self.attempt_id, State.UNKNOWN, f"{exc.code}: {detail}")
                self.event("UNKNOWN", code=exc.code, detail=detail[:300])
                return False
            if self.r.crash_after_submit:
                crashed = True
                return True
            self.step(State.VERIFYING, "VERIFYING")
            try:
                evidence = (ui.verify_private_post(mark, before) if visibility == "only_me"
                            else ui.verify_public_post(mark, caption))
            except UiStop as exc:  # after Post a failure is not knowable: UNKNOWN, never retried
                self._capture(ui, exc.code)
                self.r.journal.advance(self.attempt_id, State.UNKNOWN, f"{exc.code}: {exc.detail}")
                self.event("UNKNOWN", code=exc.code, detail=exc.detail[:300])
                return False
            evidence["value"] = f"hidden:{marker.code(self.id)}"  # readable stand-in for the invisible marker
            self.r.journal.advance(self.attempt_id, State.VERIFIED_SUCCESS, json.dumps(evidence))
            self.event("VERIFIED_SUCCESS", evidence=evidence)
            self.r.log(f"โพสต์ {self.id[:8]}: โพสต์และยืนยันผลแล้ว (รหัสซ่อน {marker.code(self.id)})")
            return False
        except UiStop as exc:  # stopped on a TikTok screen before Submit: send what the phone showed
            self._capture(ui, exc.code)
            raise
        finally:
            if not crashed:
                ui.close()

    def _needs_action(self, code: str, detail: str) -> None:
        with contextlib.suppress(TransitionError):
            self.r.journal.advance(self.attempt_id, State.NEEDS_ACTION, f"{code}: {detail}")
        with contextlib.suppress(PostStopped, ServerError, OSError):
            self.event("NEEDS_ACTION", code=code, detail=detail[:300])
        self.r.log(f"โพสต์ {self.id[:8]}: หยุดรอคนตรวจ {code}")

    def _fail(self, code: str, detail: str) -> None:
        with contextlib.suppress(TransitionError):
            self.r.journal.advance(self.attempt_id, State.RETRYABLE_FAILED, f"{code}: {detail}")
        with contextlib.suppress(PostStopped, ServerError, OSError):
            self.event("RETRYABLE_FAILED", code=code, detail=detail[:300])
        self.r.log(f"โพสต์ {self.id[:8]}: ไม่สำเร็จ {code}")

    def _cleanup(self) -> None:
        if self.remote and self.r.cleanup and self.phone is not None:
            with contextlib.suppress(AdbError):
                self.adb.shell(self.phone.adb_serial, f"rm -f '{self.remote}'")
            with contextlib.suppress(AdbError):
                self.adb.shell(self.phone.adb_serial, "am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
                                                      f"-d 'file://{self.remote}'")

    def _file(self) -> Path:
        """The exact bound file: this PC's own render when its hash matches, else a verified download."""
        clip = self.post["clip"]
        want = clip["sha256"]
        from agent import clips_folder

        # The chosen clips folder, then the old one, then a job folder moved by hand (found by its hash)
        own = clips_folder.find_clip(self.r.data_dir, clip["job_id"], clip["index"], want)
        if own is not None:
            return own
        cached = self.r.data_dir / "downloads" / f"{want}.mp4"
        if cached.is_file() and sha256_file(cached) == want:
            return cached
        if not clip.get("download_url"):
            # Q-33: clips are kept on the PC that made them; this PC does not have it (moved, deleted, other PC).
            raise PostFailed("FILE_UNAVAILABLE", "clip file not on this PC and not on the server")
        try:
            self.client.download(clip["download_url"], cached)
        except (OSError, ValueError) as exc:
            raise PostFailed("DOWNLOAD_FAILED", type(exc).__name__) from None
        if sha256_file(cached) != want:
            cached.unlink(missing_ok=True)
            raise PostFailed("FILE_HASH_MISMATCH", "downloaded file does not match the approved version")
        return cached
