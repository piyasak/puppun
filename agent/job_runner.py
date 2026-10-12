"""Agent job runner (P3.3, E-37): claim a job, make the clips on this PC, deliver them.

    claim -> inspect + captions + audio pauses + seeded selection   (job still RECEIVED)
          -> source_validated(possible clips)                       (server reserves quota)
          -> DOWNLOADING selected ranges -> ANALYZING -> RENDERING
          -> per clip: render -> checks + still on this PC -> clip_rendered(sha256, checks, path)
                       -> still (JPEG) to the server               (delivered: server settles quota, Q-33)
          -> completed | failed

One job at a time. A keep-alive thread sends `progress` events so the 300 s lease survives
long downloads and renders. LEASE_LOST / JOB_NOT_ACTIVE / a lost session stop the job at the
next step and nothing more is sent for it. Re-claiming a job after a restart resumes it: the
seed makes the same selection, uploaded clips are skipped and a local render whose hash matches
the server's report is reused.

Clips already cut (local_clips, PO 2026-10-11): a sub-folder of the videos folder, one file per clip in
EP order. Nothing is cut or rendered: each file is hashed, checked (delivery.check_ready_clip) and
linked into the job folder as clip_NN.mp4 (a hard link: no extra space; a copy when the clips folder is
on another drive), so posting finds it like any made clip. The original file is never changed or deleted.

Rendered clips stay in the clips folder chosen in the Agent (<folder>/<job id>/, Q-33) and are
never uploaded: the Agent later posts that same file (Q-15). Intermediate downloads are deleted. Error details sent to the server never contain
local paths (they can include the Windows user name).
"""

from __future__ import annotations

import contextlib
import hashlib
import shutil
import threading
import uuid
from pathlib import Path

from agent import clips_folder
from agent.server_client import ServerClient, ServerError, Session

STOP_CODES = {"LEASE_LOST", "JOB_NOT_ACTIVE", "AGENT_SESSION_ENDED"}
STAGES = ["SOURCE_VALIDATED", "DOWNLOADING", "ANALYZING", "RENDERING"]
FINISHED = {"READY_FOR_REVIEW", "FAILED", "NEEDS_ACTION", "CANCELLED"}


class JobStopped(Exception):
    """The server says this Agent must stop working on the job."""


class JobFailure(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class JobRunner:
    def __init__(self, data_dir: Path, media_dir: Path | None = None, log=print, poll_s: float = 10.0,
                 keepalive_s: float = 60.0, max_height: int = 1080, retries: int = 3, retry_wait_s: float = 2.0,
                 clips_dir: Path | None = None):
        from clipflow_worker.cooldown import Cooldown

        self.data_dir, self.media_dir, self.log = Path(data_dir), media_dir, log
        # Without FFmpeg only clip jobs wait: the Agent still connects, checks phones and posts (a PC
        # without it stopped the whole Agent with "cannot reach server", 2026-10-12).
        self._ffmpeg = self._find_ffmpeg()
        self._said_no_ffmpeg = False
        self.clips_dir = Path(clips_dir) if clips_dir else clips_folder.current(self.data_dir)
        self.poll_s, self.keepalive_s, self.max_height = poll_s, keepalive_s, max_height
        self.retries, self.retry_wait_s = retries, retry_wait_s
        self.cooldown = Cooldown(self.data_dir / "source_cooldown.json")
        self._halt = threading.Event()
        self._said_old_server = False
        self._thread: threading.Thread | None = None

    # --- background loop (used by run_connection) ------------------------------------------

    def start(self, client: ServerClient, get_session) -> None:
        self._thread = threading.Thread(target=self._loop, args=(client, get_session), daemon=True,
                                        name="clipflow-jobs")
        self._thread.start()

    def stop(self, timeout_s: float = 5.0) -> None:
        # A render in progress finishes in the background; the daemon thread dies with the process.
        self._halt.set()
        if self._thread:
            self._thread.join(timeout_s)

    def _loop(self, client: ServerClient, get_session) -> None:
        while not self._halt.is_set():
            try:
                outcome = self.run_once(client, get_session)
            except (ServerError, OSError) as exc:
                self.log(f"งาน: ติดต่อ Server ไม่ได้ ({exc}); ลองใหม่ภายหลัง")
                outcome = None
            if outcome is None:
                self._halt.wait(self.poll_s)

    @staticmethod
    def _find_ffmpeg() -> bool:
        from clipflow_worker.media import ensure_on_path

        try:
            ensure_on_path()  # before the first yt-dlp call: it caches ffmpeg detection per process
            return True
        except FileNotFoundError:
            return False

    def run_once(self, client: ServerClient, get_session) -> str | None:
        """Claim and run one job. Returns its final state, "stopped", or None when nothing was waiting."""
        if not self._ffmpeg:
            self._ffmpeg = self._find_ffmpeg()  # installed while the Agent runs: picked up on the next poll
            if not self._ffmpeg:
                if not self._said_no_ffmpeg:
                    self.log("งาน: ไม่พบ FFmpeg บนเครื่องนี้ — ยังไม่รับงานตัดคลิป (เชื่อมต่อ ตรวจโทรศัพท์ และโพสต์ทำงานตามปกติ) "
                             "เปิดหน้าต่างตั้งค่า Agent แล้วกด \"ติดตั้ง FFmpeg\" (หรือ  punpun-agent ffmpeg)")
                    self._said_no_ffmpeg = True
                return None
            self.log("งาน: พบ FFmpeg แล้ว — เริ่มรับงานตัดคลิป")
        if not clips_folder.has_room(self.clips_dir):
            gb = clips_folder.free_bytes(self.clips_dir) / 1024**3
            self.log(f"งาน: พื้นที่ว่างในโฟลเดอร์คลิปเหลือ {gb:.1f} GB (ต้องมีอย่างน้อย "
                     f"{clips_folder.MIN_FREE_BYTES // 1024**3} GB) — ยังไม่รับงานใหม่ ลบหรือย้ายคลิปเก่า หรือเปลี่ยนโฟลเดอร์ด้วย set-folder")
            return None
        session = get_session()
        if "clip_preview" not in session.features:
            # Clips stay on this PC (Q-33): a server without the still/checks endpoint could not take
            # them, and the job would fail after the whole render (seen on staging, 2026-10-09).
            if not self._said_old_server:
                self.log("งาน: Server นี้ยังไม่รองรับการเก็บคลิปไว้บนเครื่อง (ต้องอัปเดต Server ก่อน) — ยังไม่รับงานตัดคลิป")
                self._said_old_server = True
            return None
        spec = client.claim_job(session)
        if spec is None:
            return None
        return _Job(self, client, get_session, spec).run()


class _Job:
    def __init__(self, runner: JobRunner, client: ServerClient, get_session, spec: dict):
        self.r, self.client, self.get_session, self.spec = runner, client, get_session, spec
        self.id = spec["id"]
        self.state = spec["state"]
        self.reported = {c["index"]: c for c in spec.get("clips", [])}
        self.home = runner.clips_dir / self.id
        self.work = runner.data_dir / "work" / self.id
        self.stopped = threading.Event()

    # --- server calls ----------------------------------------------------------------------

    def event(self, kind: str, **payload) -> dict:
        """Send one event; network errors are retried with the same event_id (the server dedupes)."""
        body = {"event_id": uuid.uuid4().hex, "type": kind, **payload}
        for attempt in range(self.r.retries):
            try:
                resp = self.client.job_event(self.session(), self.id, body)
                self.state = resp["job"]["state"]
                return resp["job"]
            except ServerError as exc:
                if exc.code in STOP_CODES:
                    self.stopped.set()
                    raise JobStopped(exc.code) from None
                raise
            except OSError:
                if attempt + 1 == self.r.retries:
                    raise
                self.r._halt.wait(self.r.retry_wait_s * (attempt + 1))
        raise AssertionError("unreachable")

    def session(self) -> Session:
        return self.get_session()

    def check(self) -> None:
        if self.stopped.is_set():
            raise JobStopped("stopped")

    def stage(self, target: str) -> None:
        if self.state in STAGES and STAGES.index(target) > STAGES.index(self.state):
            self.event("stage", stage=target)

    def _keepalive(self, done: threading.Event) -> None:
        while not done.wait(self.r.keepalive_s):
            try:
                self.event("progress")
            except JobStopped:
                return
            except (ServerError, OSError) as exc:
                self.r.log(f"งาน {self.id[:8]}: ต่ออายุงานไม่สำเร็จ ({exc})")

    # --- the job ---------------------------------------------------------------------------

    def run(self) -> str:
        from clipflow_worker.render import RenderError
        from clipflow_worker.source import SourceError

        self.r.log(f"งาน {self.id[:8]}: เริ่มผลิตคลิป ({self.state})")
        done = threading.Event()
        threading.Thread(target=self._keepalive, args=(done,), daemon=True).start()
        try:
            self._produce()
            self.check()
            if self.state not in FINISHED:  # the server may already have ended it (T09, quota)
                self.event("completed")
        except JobStopped as exc:
            self.r.log(f"งาน {self.id[:8]}: หยุดตามที่ Server แจ้ง ({exc})")
            return "stopped"
        except SourceError as exc:
            self._fail(str(exc.code), exc.detail)
        except RenderError as exc:
            self._fail("RENDER_MISMATCH", str(exc).split(":", 1)[-1])
        except JobFailure as exc:
            self._fail(exc.code, exc.detail)
        except ServerError as exc:  # the server refused a report: tell it why we gave up
            self.r.log(f"งาน {self.id[:8]}: Server ปฏิเสธ {exc}")
            self._fail("AGENT_ERROR", exc.code)
        except Exception as exc:  # noqa: BLE001 - reported to the server; full detail stays in the local log
            self.r.log(f"งาน {self.id[:8]}: ผิดพลาด {exc!r}")
            self._fail("AGENT_ERROR", type(exc).__name__)
        finally:
            done.set()
            shutil.rmtree(self.work, ignore_errors=True)
        self.r.log(f"งาน {self.id[:8]}: {self.state}")
        return self.state

    def _fail(self, code: str, detail: str) -> None:
        with contextlib.suppress(JobStopped):
            self.event("failed", code=code, detail=(detail or "")[:300])

    def _source(self) -> tuple[str | None, Path | None]:
        from clipflow_worker.source import SourceError, SourceErrorCode

        src = self.spec["source"]
        if src["kind"] != "local_file":
            return src["url"], None
        name = src.get("file_name") or ""
        folder = self.r.media_dir
        path = (folder / name) if folder else None
        # The server only accepts bare file names; refuse anything that would leave the media folder.
        if path is None or Path(name).name != name or not path.is_file():
            raise SourceError(SourceErrorCode.NOT_FOUND,
                              f"ไม่พบไฟล์ {name} ในโฟลเดอร์วิดีโอของ Agent (--media-dir)")
        return None, path

    def _guarded(self, url: str | None, action):
        if url is None:
            return action()
        from clipflow_worker.poc import guarded

        return guarded(self.r.cooldown, url, action)

    def _produce(self) -> None:
        if self.spec["source"]["kind"] == "local_clips":
            self._produce_ready()
            return
        from clipflow_worker import pipeline
        from clipflow_worker.render import RenderError, Template

        spec = self.spec
        url, local = self._source()
        p = self._guarded(url, lambda: pipeline.plan(
            work=self.work, count=spec["requested_clips"], seed=spec["seed"], min_len=spec["clip_min_s"],
            max_len=spec["clip_max_s"], url=url, local=local,
            whole=bool(spec.get("auto_clips")),  # Q-32: split the whole source; the count follows it
        ))
        self.check()
        possible = len(p.selection.segments)
        if self.state == "RECEIVED":
            job = self.event("source_validated", duration_s=p.info.duration_s, possible_clips=possible)
            if self.state in FINISHED:  # too short (T09) or quota exhausted: nothing to make
                return
            planned = job["planned_clips"]
        else:
            planned = spec["planned_clips"] or 0
            if possible < planned:  # same seed, different source content: never mix two selections
                raise JobFailure("SOURCE_CHANGED", f"ต้นฉบับตัดได้ {possible} คลิป แต่วางแผนไว้ {planned}")
        remake = set(spec.get("remake") or [])  # start again (PO 2026-10-10): files missing on this PC
        todo = [(i, s) for i, s in enumerate(p.selection.segments[:planned], start=1)
                if i in remake or not self.reported.get(i, {}).get("uploaded")]
        if remake:
            self._bring_back_moved(remake)
            self.r.log(f"งาน {self.id[:8]}: เริ่มใหม่ — หาหรือทำไฟล์คลิป {sorted(remake)} ใหม่")

        self.stage("DOWNLOADING")
        parts = {}
        for index, segment in todo:
            if self._kept(index):
                continue  # the file is here: re-report it, nothing to download
            parts[index] = self._guarded(url, lambda segment=segment: pipeline.fetch_part(p, segment,
                                                                                           self.r.max_height))
            self.check()
        self.stage("ANALYZING")
        self.stage("RENDERING")

        tpl = Template(burn_subtitles=spec["subtitles"])
        self.home.mkdir(parents=True, exist_ok=True)
        failures = []
        for index, segment in todo:
            self.check()
            out = self.home / f"clip_{index:02d}.mp4"
            earlier = self.reported.get(index)
            if self._kept(index):
                # Rendered and reported before a restart: check it again and send what is missing.
                self._deliver(index, out, earlier["duration_ms"], resend=True)
                self.r.log(f"งาน {self.id[:8]}: ส่งคลิป {index}/{planned} แล้ว (ไฟล์เดิม)")
                continue
            try:
                result, metadata, _ = pipeline.render(p, index, segment, *parts[index], out, tpl,
                                                      title=self.spec.get("title"))
                out.with_suffix(".ass").unlink(missing_ok=True)  # render's subtitle file: not for the customer's folder
            except RenderError as exc:  # keep going: the other clips are still worth delivering
                failures.append(index)
                self.r.log(f"งาน {self.id[:8]}: คลิป {index} render ไม่ผ่าน ({exc})")
                continue
            if earlier and earlier["sha256"] != result.sha256:
                self.r.log(f"งาน {self.id[:8]}: คลิป {index} render ใหม่ได้ไฟล์ต่างจากเดิม แจ้ง Server ใหม่")
            self.check()
            duration_ms = round(result.duration_s * 1000)
            checks = self._checks(index, out, duration_ms)
            self.event("clip_rendered", index=index, start_ms=round(segment.start * 1000),
                       end_ms=round(segment.end * 1000), duration_ms=duration_ms,
                       sha256=result.sha256, size_bytes=out.stat().st_size,
                       template_version=result.template_version, title=metadata["title"],
                       caption=metadata["caption"], hashtags=metadata["hashtags"],
                       checks=checks, local_path=str(out))
            self._deliver(index, out, duration_ms)
            self.r.log(f"งาน {self.id[:8]}: ส่งคลิป {index}/{planned} แล้ว")
        if failures and len(failures) == len(todo) and not any(c.get("uploaded") for c in self.reported.values()):
            raise JobFailure("RENDER_FAILED", f"render ไม่ผ่านทุกคลิป ({failures})")

    def _ready_folder(self) -> Path:
        from clipflow_worker.source import SourceError, SourceErrorCode

        name = self.spec["source"].get("folder") or self.spec["source"].get("file_name") or ""
        folder = (self.r.media_dir / name) if self.r.media_dir else None
        # The server only accepts bare folder names; refuse anything that would leave the videos folder.
        if folder is None or Path(name).name != name or not folder.is_dir():
            raise SourceError(SourceErrorCode.NOT_FOUND, f"ไม่พบโฟลเดอร์ {name} ในโฟลเดอร์วิดีโอของ Agent")
        return folder

    def _produce_ready(self) -> None:
        """A folder of clips already cut: report, check, link and deliver each one in EP order."""
        from agent.library import clips_in
        from clipflow_worker import delivery

        files = clips_in(self._ready_folder())
        if self.state == "RECEIVED":
            total = sum(delivery.probe_duration_s(f) for f in files)
            job = self.event("source_validated", duration_s=max(1, round(total)), possible_clips=len(files))
            if self.state in FINISHED:  # empty folder or quota: nothing to send
                return
            planned = job["planned_clips"]
        else:
            planned = self.spec["planned_clips"] or 0
            if len(files) < planned:
                raise JobFailure("SOURCE_CHANGED", f"โฟลเดอร์มี {len(files)} คลิป แต่วางแผนไว้ {planned}")
        self.stage("RENDERING")
        self.home.mkdir(parents=True, exist_ok=True)
        for index, src in enumerate(files[:planned], start=1):
            self.check()
            earlier = self.reported.get(index)
            if earlier and earlier.get("uploaded"):
                continue
            out = self.home / f"clip_{index:02d}.mp4"
            sha = _sha256(src)
            if not (out.is_file() and _sha256(out) == sha):
                out.unlink(missing_ok=True)
                try:
                    out.hardlink_to(src)  # same drive: no extra space, the original stays where it is
                except OSError:
                    shutil.copy2(src, out)  # the clips folder is on another drive
            duration_ms = round(delivery.probe_duration_s(out) * 1000)
            checks = delivery.check_ready_clip(out)
            self.event("clip_rendered", index=index, start_ms=0, end_ms=duration_ms, duration_ms=duration_ms,
                       sha256=sha, size_bytes=out.stat().st_size, template_version="ready-cut",
                       title=src.stem, caption=src.stem, hashtags=[], checks=checks, local_path=str(out))
            still = self.home / f"clip_{index:02d}.jpg"
            delivery.contact_sheet(out, still, max(duration_ms / 1000, 0.1))
            self._upload(index, still)
            self.r.log(f"งาน {self.id[:8]}: ส่งคลิป {index}/{planned} ({src.name}) แล้ว")

    def _kept(self, index: int) -> bool:
        """This clip's reported file is in the job folder with the reported hash."""
        earlier = self.reported.get(index)
        out = self.home / f"clip_{index:02d}.mp4"
        return bool(earlier) and out.is_file() and _sha256(out) == earlier["sha256"]

    def _bring_back_moved(self, indexes: set[int]) -> None:
        """A job folder moved by hand: put the files whose hash matches back where posting looks first."""
        self.home.mkdir(parents=True, exist_ok=True)
        for index in sorted(indexes):
            earlier = self.reported.get(index)
            out = self.home / f"clip_{index:02d}.mp4"
            if not earlier or out.is_file():
                continue
            found = clips_folder.find_clip(self.r.data_dir, self.id, index, earlier["sha256"])
            if found is not None and found != out:
                shutil.move(str(found), str(out))
                still = found.with_suffix(".jpg")
                if still.is_file():
                    shutil.move(str(still), str(out.with_suffix(".jpg")))
                self.r.log(f"งาน {self.id[:8]}: พบคลิป {index} ที่ {found.parent} ย้ายกลับมาที่ {self.home}")

    def _checks(self, index: int, path: Path, duration_ms: int) -> dict:
        """The server's file checks, made here because the file never leaves this PC (Q-33)."""
        from clipflow_worker import delivery

        spec = self.spec
        stretch = 1.2 if spec.get("auto_clips") and index == spec.get("planned_clips") else 1
        return delivery.check_clip(path, reported_duration_ms=duration_ms, clip_min_s=spec["clip_min_s"],
                                   clip_max_s=spec["clip_max_s"] * stretch)

    def _deliver(self, index: int, path: Path, duration_ms: int, resend: bool = False) -> None:
        if resend:  # after a restart: the report may have gone out without checks (or before Q-33)
            earlier = self.reported[index]
            self.event("clip_rendered", index=index, start_ms=earlier["start_ms"], end_ms=earlier["end_ms"],
                       duration_ms=earlier["duration_ms"], sha256=earlier["sha256"], size_bytes=path.stat().st_size,
                       template_version=earlier["template_version"], title=earlier.get("title") or "",
                       checks=self._checks(index, path, earlier["duration_ms"]), local_path=str(path))
        from clipflow_worker import delivery

        still = self.home / f"clip_{index:02d}.jpg"
        delivery.contact_sheet(path, still, max(duration_ms / 1000, 0.1))
        self._upload(index, still)

    def _upload(self, index: int, still: Path) -> None:
        for attempt in range(self.r.retries):
            try:
                self.client.upload_preview(self.session(), self.id, index, still)
                return
            except ServerError as exc:
                if exc.code in STOP_CODES:
                    self.stopped.set()
                    raise JobStopped(exc.code) from None
                raise
            except OSError:
                if attempt + 1 == self.r.retries:
                    raise
                self.r._halt.wait(self.r.retry_wait_s * (attempt + 1))
