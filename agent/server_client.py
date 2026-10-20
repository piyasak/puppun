"""Outbound HTTPS client from the Agent to the ClipFlow server (E-09: polling, no inbound ports).

Only the standard library is used. The Agent token and session token are sent in the JSON
body / Authorization header, never in a URL, and never printed.
"""

from __future__ import annotations

import contextlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from agent import __version__ as AGENT_VERSION  # noqa: E402,N812
from agent import net  # noqa: E402


class ServerError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(f"{status} {code}: {message}")
        self.status, self.code, self.message, self.details = status, code, message, details or {}

    @property
    def reason(self) -> str | None:
        return self.details.get("reason")


def check_server_url(url: str) -> str:
    """HTTPS only, except plain HTTP to this machine for local development."""
    parts = urlsplit(url)
    local = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("server URL must use https:// (http:// is allowed only for localhost)")
    if parts.username or parts.password or parts.query:
        raise ValueError("server URL must not contain credentials or a query string")
    return url.rstrip("/")


@dataclass
class Session:
    token: str
    generation: int
    environment: dict
    heartbeat_interval_s: int
    features: tuple[str, ...] = ()  # what the server supports; empty from servers before Q-33


JOB_KINDS = ("youtube", "bilibili", "local_file", "local_clips")


class ServerClient:
    def __init__(self, server_url: str, timeout_s: float = 15.0):
        self.base = check_server_url(server_url)
        self.timeout_s = timeout_s

    def _post(self, path: str, body: dict, bearer: str | None = None) -> dict:
        return self._send("POST", path, json.dumps(body).encode(), "application/json", bearer)

    def _send(self, method: str, path: str, data, content_type: str, bearer: str | None,
              extra_headers: dict | None = None, timeout_s: float | None = None) -> dict:
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": content_type, "User-Agent": f"ClipFlowAgent/{AGENT_VERSION}",
                     **({"Authorization": f"Bearer {bearer}"} if bearer else {}), **(extra_headers or {})},
        )
        try:
            with net.urlopen(req, timeout=timeout_s or self.timeout_s) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read() or b"{}")
            except json.JSONDecodeError:
                err = {}
            raise ServerError(exc.code, err.get("code", "HTTP_ERROR"), err.get("message", str(exc)),
                              err.get("details")) from None

    def pair(self, code: str, computer_name: str) -> dict:
        """A pairing code from the web -> this PC's own Agent token (+ username, Environment)."""
        return self._post("/v1/agent/pair", {"code": code, "computer_name": computer_name})

    def authenticate(self, username: str, agent_token: str, installation_id: str) -> Session:
        body = self._post("/v1/agent/authenticate", {
            "username": username, "token": agent_token, "installation_id": installation_id,
            "agent_version": AGENT_VERSION,
        })
        return Session(body["session_token"], body["generation"], body["environment"], body["heartbeat_interval_s"],
                       tuple(body.get("features") or ()))

    def heartbeat(self, session: Session) -> dict:
        return self._post("/v1/agent/heartbeat", {"generation": session.generation}, bearer=session.token)

    def register_device(self, session: Session, serial: str, adb_state: str, model: str | None,
                        android_version: str | None, thai_keyboard: bool | None = None) -> dict:
        return self._post("/v1/agent/devices/register", {
            "serial": serial, "adb_state": adb_state, "model": model, "android_version": android_version,
            "thai_keyboard": thai_keyboard,
        }, bearer=session.token)

    def report_devices(self, session: Session, states: dict[str, str]) -> dict:
        return self._post("/v1/agent/devices/report", {"devices": states}, bearer=session.token)

    def claim_job(self, session: Session) -> dict | None:
        # kinds (0.5.0): this Agent can also send a folder of clips already cut (local_clips).
        return self._post("/v1/agent/jobs/claim", {"kinds": list(JOB_KINDS)}, bearer=session.token)["job"]

    def report_library(self, session: Session, library: dict) -> dict:
        """Names and sizes in the videos folder (PO 2026-10-11), never paths or files."""
        return self._send("PUT", "/v1/agent/library", json.dumps(library).encode(), "application/json", session.token)

    def job_event(self, session: Session, job_id: str, event: dict) -> dict:
        return self._post(f"/v1/agent/jobs/{job_id}/events", event, bearer=session.token)

    def upload_clip(self, session: Session, job_id: str, index: int, path: Path) -> dict:
        """Streams the file; the server hashes it and compares with the clip_rendered report."""
        size = path.stat().st_size
        with open(path, "rb") as fh:
            return self._send("PUT", f"/v1/agent/jobs/{job_id}/clips/{index}/file", fh, "video/mp4",
                              session.token, {"Content-Length": str(size)}, timeout_s=max(60.0, size / 1e6))

    def upload_preview(self, session: Session, job_id: str, index: int, path: Path) -> dict:
        """Q-33: the still of a clip whose file stays on this PC (its checks went with clip_rendered)."""
        return self._send("PUT", f"/v1/agent/jobs/{job_id}/clips/{index}/preview", path.read_bytes(), "image/jpeg",
                          session.token, {}, timeout_s=60.0)

    def claim_post(self, session: Session, ready_serials: list[str]) -> dict | None:
        # can_post_live (Q-42): this Agent can carry out a post the server hands out live under a grant.
        # can_skip_account_check (Q-48, 0.5.7): this Agent posts without the account check when the server says so.
        return self._post("/v1/agent/posts/claim", {"ready_serials": ready_serials, "can_post_live": True,
                                                    "can_skip_account_check": True, "can_post_public": True},
                          bearer=session.token)["post"]

    def post_event(self, session: Session, post_id: str, event: dict) -> dict:
        return self._post(f"/v1/agent/posts/{post_id}/events", event, bearer=session.token)

    def ui_profile(self, session: Session) -> dict | None:
        """Q-50: the latest TikTok UI profile {"version", "body"}, or None when the server has none yet."""
        try:
            return self._send("GET", "/v1/agent/ui-profile", None, "application/json", session.token)
        except ServerError as exc:
            if exc.status == 404:
                return None
            raise

    # --- screen diagnostics (PO 2026-10-16) ---------------------------------------------------------------

    def diagnostic_failure(self, session: Session, serial: str, post_id: str | None, code: str) -> str:
        return self._post("/v1/agent/diagnostics", {"serial": serial, "item_id": post_id, "code": code[:40]},
                          bearer=session.token)["id"]

    def diagnostic_requested(self, session: Session, ready_serials: list[str]) -> dict | None:
        return self._post("/v1/agent/diagnostics/requested", {"ready_serials": ready_serials},
                          bearer=session.token)["diagnostic"]

    def diagnostic_file(self, session: Session, diag_id: str, step: int, name: str, ext: str, data: bytes) -> dict:
        kind = "image/png" if ext == "png" else "text/plain"
        return self._send("PUT", f"/v1/agent/diagnostics/{diag_id}/files/{step}/{name}.{ext}", data, kind,
                          session.token, {}, timeout_s=60.0)

    def diagnostic_done(self, session: Session, diag_id: str, note: str | None = None, error: str | None = None) -> dict:
        return self._post(f"/v1/agent/diagnostics/{diag_id}/done", {"note": note, "error": error}, bearer=session.token)

    def account_stats(self, session: Session, serial: str, numbers: dict) -> dict:
        """Q-52: followers / following / likes / newest videos' views read on a phone's Profile."""
        return self._post("/v1/agent/account-stats", {"serial": serial, **numbers}, bearer=session.token)

    def post_state(self, session: Session, post_id: str) -> dict:
        """Where one of this Environment's posts stands: state, reason, attempt."""
        return self._send("GET", f"/v1/agent/posts/{post_id}", None, "application/json", session.token)

    def devices(self, session: Session) -> list[dict]:
        """This Environment's phones with the names set on the web (for the phone screen windows)."""
        return self._send("GET", "/v1/agent/devices", None, "application/json", session.token)["items"]

    def deletable_clips(self, session: Session) -> list[dict]:
        """Clips this PC keeps whose job deletes them once posted, and whose posts are all settled."""
        return self._send("GET", "/v1/agent/clips/deletable", None, "application/json", session.token)["items"]

    def clip_file_deleted(self, session: Session, clip_id: str, found: bool) -> dict:
        return self._post(f"/v1/agent/clips/{clip_id}/file-deleted", {"found": found}, bearer=session.token)

    def download(self, url: str, dest: Path, timeout_s: float = 300.0) -> None:
        """Fetch a short-lived signed link the server handed out (no Agent credentials are sent)."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise ValueError("download link must be http(s)")
        req = urllib.request.Request(url, headers={"User-Agent": f"ClipFlowAgent/{AGENT_VERSION}"})
        tmp = dest.with_suffix(dest.suffix + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with net.urlopen(req, timeout=timeout_s) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(1024 * 1024):
                out.write(chunk)
        tmp.replace(dest)

    def end(self, session: Session) -> None:
        # Best effort; the server expires the session after 90 s anyway.
        with contextlib.suppress(ServerError, OSError):
            self._post("/v1/agent/session/end", {}, bearer=session.token)


@dataclass
class RunResult:
    heartbeats: int
    stopped_because: str
    environment: dict | None


# Waits between tries while the server cannot be reached (network down, timeouts, a 5xx while it restarts).
RETRY_WAITS_S = (5, 10, 20, 30, 60)


def temporary(exc: Exception) -> bool:
    """A network problem or the server failing for a moment: try again, never stop the Agent for it."""
    if isinstance(exc, ServerError):
        return exc.status >= 500 or exc.status == 429
    return isinstance(exc, OSError)


def _wait_s(failures: int) -> float:
    return RETRY_WAITS_S[min(failures, len(RETRY_WAITS_S)) - 1]


def run_connection(client: ServerClient, username: str, agent_token: str, installation_id: str,
                   duration_s: float | None, sleep=time.sleep, clock=time.monotonic, log=print,
                   on_session=None, periodic_s: float = 60.0, worker=None) -> RunResult:
    """Authenticate, then heartbeat until `duration_s` elapses or the server ends the session.

    A superseded, revoked or deregistered session stops the loop instead of signing in again:
    re-authenticating automatically would steal the session back from the newer process.
    An expired session (e.g. the PC slept) signs in again once.

    The network or the server failing for a while (timeouts, 5xx, 429) never stops the Agent: it says so and
    tries again with growing waits (RETRY_WAITS_S), signing in again if the session expired meanwhile. Before
    0.9.1 one read timeout ended the session and closed the Agent mid-job (staging, 2026-10-19).

    `on_session(client, session)` runs right after sign-in and then every `periodic_s` seconds
    (the phone check, Q-25).

    `worker` (the job runner, P3.3) works in its own thread and always uses the current session;
    the heartbeat stays on this thread so a long render never lets the session expire.
    """
    started = clock()

    def in_time() -> bool:
        return duration_s is None or clock() - started < duration_s

    failures = 0
    while True:  # the first sign-in: wait for the network / server instead of closing
        try:
            session = client.authenticate(username, agent_token, installation_id)
            break
        except (ServerError, OSError) as exc:
            if not temporary(exc) or not in_time():
                raise
            failures += 1
            log(f"ติดต่อ server ไม่ได้ ({exc}) — ลองใหม่ใน {_wait_s(failures)} วินาที")
            sleep(_wait_s(failures))
    current = [session]
    log(f"connected: environment={session.environment['name']} generation={session.generation}")
    failures = 0
    workers = [] if worker is None else worker if isinstance(worker, list) else [worker]
    try:
        if on_session:
            with contextlib.suppress(ServerError, OSError):
                on_session(client, session)
        for w in workers:
            w.start(client, lambda: current[0])
        beats, reauthed = 0, False
        last_check = clock()
        while in_time():
            sleep(_wait_s(failures) if failures else session.heartbeat_interval_s)
            try:
                try:
                    client.heartbeat(session)
                except ServerError as exc:
                    if exc.code == "AGENT_SESSION_ENDED" and exc.reason == "expired" and not reauthed:
                        session = client.authenticate(username, agent_token, installation_id)
                        current[0], reauthed = session, True
                        log(f"session expired; reconnected: generation={session.generation}")
                        continue
                    raise
                if failures:
                    log("ติดต่อ server ได้อีกครั้ง")
                failures = 0
                beats += 1
                reauthed = False
                if on_session and clock() - last_check >= periodic_s:
                    on_session(client, session)
                    last_check = clock()
            except (ServerError, OSError) as exc:
                if temporary(exc):
                    failures += 1
                    log(f"ติดต่อ server ไม่ได้ชั่วคราว ({exc}) — Agent ยังทำงานต่อ ลองใหม่ใน {_wait_s(failures)} วินาที")
                    continue
                log(f"stopped by server: {exc.code} {exc.reason or ''} — {exc.message}")
                return RunResult(beats, exc.reason or exc.code, session.environment)
        return RunResult(beats, "duration_elapsed", session.environment)
    finally:
        for w in workers:
            w.stop()
        with contextlib.suppress(ServerError, OSError):
            client.end(session)
