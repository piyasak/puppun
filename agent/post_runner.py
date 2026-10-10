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

There is no Submit step here: the server only runs in dry-run (E-40), and the TikTok UI steps
(account check, Thai caption, Post, verification) are P5.4 and need a separate authorization.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
import time
import uuid
from pathlib import Path

from agent.adb import Adb, AdbError, normalize_serial
from agent.attempt import AttemptJournal, State, TransitionError
from agent.authorization import GrantRefused
from agent.compat import check_phone
from agent.device_registry import discover
from agent.server_client import ServerClient, ServerError
from agent.tiktok_ui import TikTokUi, UiStop, media_id

STOP_CODES = {"LEASE_LOST", "ITEM_NOT_ACTIVE", "AGENT_SESSION_ENDED"}
FREE_SPACE_EVERY_S = 300.0


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
                 grant_source=None, crash_after_submit: bool = False):
        self.data_dir, self.adb_factory, self.log = Path(data_dir), adb_factory, log
        self.poll_s, self.cleanup = poll_s, cleanup
        # Q-27: in dry runs, also go through TikTok up to (never including) Post, then close it.
        self.ui_rehearsal = ui_rehearsal
        self.ui_factory = ui_factory
        # Q-29: a live post needs a one-time grant (agent.authorization.take) handed in explicitly.
        self.grant_source = grant_source
        self.crash_after_submit = crash_after_submit  # fault injection for G5-04: stop dead after Post
        self.retries, self.retry_wait_s = retries, retry_wait_s
        self.journal = AttemptJournal(self.data_dir / "attempts.jsonl")
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None

    # --- background loop -------------------------------------------------------------------

    def start(self, client: ServerClient, get_session) -> None:
        self._thread = threading.Thread(target=self._loop, args=(client, get_session), daemon=True,
                                        name="clipflow-posts")
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout_s)

    def _loop(self, client: ServerClient, get_session) -> None:
        next_free = 0.0
        while not self._halt.is_set():
            if time.monotonic() >= next_free:
                next_free = time.monotonic() + FREE_SPACE_EVERY_S
                try:
                    self.delete_posted_clips(client, get_session)
                except (ServerError, OSError) as exc:
                    self.log(f"ลบคลิปหลังโพสต์: ทำต่อไม่ได้ชั่วคราว ({exc}); ลองใหม่ภายหลัง")
            try:
                outcome = self.run_once(client, get_session)
            except (ServerError, OSError, AdbError) as exc:
                self.log(f"โพสต์: ทำต่อไม่ได้ชั่วคราว ({exc}); ลองใหม่ภายหลัง")
                outcome = None
            if outcome is None:
                self._halt.wait(self.poll_s)  # idle: E-41 (<= 15 s)

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

    def run_once(self, client: ServerClient, get_session) -> str | None:
        """Claim and carry out one post. Returns its final state, "stopped", or None if nothing was due."""
        adb = self.adb_factory()
        phones = {normalize_serial(p.hw_serial): p for p in discover(adb) if p.state == "device" and p.hw_serial}
        if not phones:
            return None
        post = client.claim_post(get_session(), [p.hw_serial for p in phones.values()])
        if post is None:
            return None
        phone = phones.get(normalize_serial(post["device"]["serial"]))
        return _Post(self, client, get_session, post, adb, phone).run()


class _Post:
    def __init__(self, runner: PostRunner, client: ServerClient, get_session, post: dict, adb: Adb, phone):
        self.r, self.client, self.get_session, self.post = runner, client, get_session, post
        self.adb, self.phone = adb, phone
        self.id = post["id"]
        self.attempt_id = f"{self.id}-{post['attempt']}"
        self.state = post["state"]
        self.remote: str | None = None

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
        finally:
            ui.close()

    def _check_compat(self) -> None:
        """Never drive TikTok on a phone/app combination that was not tested (D03, NF-10, T25)."""
        report = self.adb.doctor(self.phone.adb_serial)
        verdict = check_phone(report.model, report.android_release, report.tiktok_package, report.tiktok_version)
        if not verdict.supported:
            raise UiStop("UNSUPPORTED_DEVICE", verdict.reason)

    def _ui(self):
        return (self.r.ui_factory or (lambda adb, serial: TikTokUi(adb, serial)))(self.adb, self.phone.adb_serial)

    def _caption(self, marker: str | None = None) -> str:
        text = self.post["text"]
        parts = [text["caption"], *[t for t in text["hashtags"] if t not in text["caption"]]]
        return " ".join([*parts, *([marker] if marker else [])]).strip()

    def _live(self) -> bool:
        """The authorized post (Q-29). Returns True when a crash after Post was simulated."""
        if self.r.grant_source is None:
            raise PostFailed("POSTING_NOT_AVAILABLE", "no posting grant on this Agent")
        ui = self._ui()
        marker = "cf" + self.id.replace("-", "")[:6]  # ties the post to this attempt (PRD §H, Q-21)
        caption = self._caption(marker)
        crashed = False
        try:
            ui.check_account(self.post["device"]["expected_account"])
            before = ui.private_count()
            found = media_id(self.adb, self.phone.adb_serial, self.remote.rsplit("/", 1)[-1])
            if found is None:
                raise PostFailed("GALLERY_NOT_FOUND", "no MediaStore id for the clip")
            ui.open_post_screen(found)
            ui.set_only_me()
            ui.type_caption(caption)
            # The session must be alive before a grant is spent: a grant used and then refused by the server
            # is lost (QA run 2026-10-08: the session expired during the TikTok steps).
            try:
                self.client.heartbeat(self.get_session())
            except ServerError as exc:
                if exc.code in STOP_CODES:
                    raise PostStopped(exc.code) from None
                raise
            try:  # used and fsynced first: an exhausted grant stops here, before the server hears SUBMITTING
                grant = self.r.grant_source(f"post {self.id}")
            except GrantRefused as exc:
                raise PostFailed("NO_GRANT", str(exc)) from None
            self.event("SUBMITTING")  # the server checks approval again (PRD §G.6); a refusal stops here
            self.r.journal.advance(self.attempt_id, State.SUBMITTING, f"grant {grant.decision} #{grant.number}")
            ui.submit(grant, caption)
            if self.r.crash_after_submit:
                crashed = True
                return True
            self.step(State.VERIFYING, "VERIFYING")
            try:
                evidence = ui.verify_private_post(marker, before)
            except UiStop as exc:  # after Post a failure is not knowable: UNKNOWN, never retried
                self.r.journal.advance(self.attempt_id, State.UNKNOWN, f"{exc.code}: {exc.detail}")
                self.event("UNKNOWN", code=exc.code, detail=exc.detail[:300])
                return False
            self.r.journal.advance(self.attempt_id, State.VERIFIED_SUCCESS, json.dumps(evidence))
            self.event("VERIFIED_SUCCESS", evidence=evidence)
            self.r.log(f"โพสต์ {self.id[:8]}: โพสต์และยืนยันผลแล้ว ({marker})")
            return False
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

        for folder in clips_folder.search_order(self.r.data_dir):  # the chosen clips folder, then the old one
            own = folder / clip["job_id"] / f"clip_{clip['index']:02d}.mp4"
            if own.is_file() and sha256_file(own) == want:
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
