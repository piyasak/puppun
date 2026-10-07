"""Outbound HTTPS client from the Agent to the ClipFlow server (E-09: polling, no inbound ports).

Only the standard library is used. The Agent token and session token are sent in the JSON
body / Authorization header, never in a URL, and never printed.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

AGENT_VERSION = "0.1.0"


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


class ServerClient:
    def __init__(self, server_url: str, timeout_s: float = 15.0):
        self.base = check_server_url(server_url)
        self.timeout_s = timeout_s

    def _post(self, path: str, body: dict, bearer: str | None = None) -> dict:
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": f"ClipFlowAgent/{AGENT_VERSION}",
                     **({"Authorization": f"Bearer {bearer}"} if bearer else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read() or b"{}")
            except json.JSONDecodeError:
                err = {}
            raise ServerError(exc.code, err.get("code", "HTTP_ERROR"), err.get("message", str(exc)),
                              err.get("details")) from None

    def authenticate(self, username: str, agent_token: str, installation_id: str) -> Session:
        body = self._post("/v1/agent/authenticate", {
            "username": username, "token": agent_token, "installation_id": installation_id,
            "agent_version": AGENT_VERSION,
        })
        return Session(body["session_token"], body["generation"], body["environment"], body["heartbeat_interval_s"])

    def heartbeat(self, session: Session) -> dict:
        return self._post("/v1/agent/heartbeat", {"generation": session.generation}, bearer=session.token)

    def register_device(self, session: Session, serial: str, adb_state: str, model: str | None,
                        android_version: str | None) -> dict:
        return self._post("/v1/agent/devices/register", {
            "serial": serial, "adb_state": adb_state, "model": model, "android_version": android_version,
        }, bearer=session.token)

    def report_devices(self, session: Session, states: dict[str, str]) -> dict:
        return self._post("/v1/agent/devices/report", {"devices": states}, bearer=session.token)

    def end(self, session: Session) -> None:
        try:
            self._post("/v1/agent/session/end", {}, bearer=session.token)
        except (ServerError, OSError):
            pass  # best effort; the server expires the session after 90 s anyway


@dataclass
class RunResult:
    heartbeats: int
    stopped_because: str
    environment: dict | None


def run_connection(client: ServerClient, username: str, agent_token: str, installation_id: str,
                   duration_s: float | None, sleep=time.sleep, clock=time.monotonic, log=print) -> RunResult:
    """Authenticate, then heartbeat until `duration_s` elapses or the server ends the session.

    A superseded, revoked or deregistered session stops the loop instead of signing in again:
    re-authenticating automatically would steal the session back from the newer process.
    An expired session (e.g. the PC slept) signs in again once.
    """
    session = client.authenticate(username, agent_token, installation_id)
    log(f"connected: environment={session.environment['name']} generation={session.generation}")
    started, beats, reauthed = clock(), 0, False
    try:
        while duration_s is None or clock() - started < duration_s:
            sleep(session.heartbeat_interval_s)
            try:
                client.heartbeat(session)
                beats += 1
                reauthed = False
            except ServerError as exc:
                if exc.code == "AGENT_SESSION_ENDED" and exc.reason == "expired" and not reauthed:
                    session, reauthed = client.authenticate(username, agent_token, installation_id), True
                    log(f"session expired; reconnected: generation={session.generation}")
                    continue
                log(f"stopped by server: {exc.code} {exc.reason or ''} — {exc.message}")
                return RunResult(beats, exc.reason or exc.code, session.environment)
        return RunResult(beats, "duration_elapsed", session.environment)
    finally:
        client.end(session)
