"""Agent identity, process lock, server URL rules and the connection loop (logic only, no server)."""

import subprocess
import sys
import textwrap
import uuid

import pytest

from agent.identity import ProcessLock, load_or_create_installation_id
from agent.server_client import ServerError, Session, check_server_url, run_connection


def test_installation_id_survives_restarts(tmp_path):
    first = load_or_create_installation_id(tmp_path)
    assert uuid.UUID(first) and load_or_create_installation_id(tmp_path) == first


def test_corrupt_installation_id_is_replaced(tmp_path):
    (tmp_path / "installation_id").write_text("not-a-uuid")
    assert uuid.UUID(load_or_create_installation_id(tmp_path))


def test_second_process_cannot_take_the_lock(tmp_path):
    child = textwrap.dedent(f"""
        import sys
        from pathlib import Path
        from agent.identity import AlreadyRunning, ProcessLock
        try:
            ProcessLock(Path(r"{tmp_path}")).acquire()
        except AlreadyRunning:
            sys.exit(3)
        sys.exit(0)
    """)
    with ProcessLock(tmp_path):
        assert subprocess.run([sys.executable, "-c", child]).returncode == 3
    # Released: another process can start now.
    assert subprocess.run([sys.executable, "-c", child]).returncode == 0


def test_lock_is_reentrant_only_after_release(tmp_path):
    lock = ProcessLock(tmp_path).acquire()
    lock.release()
    ProcessLock(tmp_path).acquire().release()


@pytest.mark.parametrize("url,ok", [
    ("https://api.example.com", True),
    ("http://127.0.0.1:8000", True),
    ("http://localhost:8000", True),
    ("http://api.example.com", False),          # token would travel in clear text
    ("https://user:pw@api.example.com", False),
    ("https://api.example.com/?token=x", False),
    ("ftp://api.example.com", False),
])
def test_server_url_rules(url, ok):
    if ok:
        assert check_server_url(url)
    else:
        with pytest.raises(ValueError):
            check_server_url(url)


class FakeClient:
    def __init__(self, failures):
        self.failures = list(failures)  # ServerError or None per heartbeat
        self.auths = 0
        self.ended = []

    def authenticate(self, *_):
        self.auths += 1
        return Session(f"cfas_{self.auths}", self.auths, {"id": "e", "name": "office"}, 15)

    def heartbeat(self, session):
        failure = self.failures.pop(0) if self.failures else None
        if failure:
            raise failure

    def end(self, session):
        self.ended.append(session.token)


def _run(client, duration=100):
    t = [0.0]
    return run_connection(client, "u", "cfat_x", "inst", duration, sleep=lambda s: t.__setitem__(0, t[0] + s),
                          clock=lambda: t[0], log=lambda *_: None)


def test_runs_until_duration_and_ends_the_session():
    client = FakeClient([])
    result = _run(client, duration=60)
    assert result.stopped_because == "duration_elapsed" and result.heartbeats == 4
    assert client.ended == ["cfas_1"]


@pytest.mark.parametrize("reason", ["superseded", "token_revoked", "deregistered"])
def test_server_ended_session_stops_without_signing_in_again(reason):
    client = FakeClient([ServerError(401, "AGENT_SESSION_ENDED", "x", {"reason": reason})])
    result = _run(client)
    assert result.stopped_because == reason and client.auths == 1


def test_expired_session_reconnects_once_then_continues():
    expired = ServerError(401, "AGENT_SESSION_ENDED", "x", {"reason": "expired"})
    client = FakeClient([None, expired, None, expired, expired])
    result = _run(client, duration=300)
    assert client.auths == 3 and result.stopped_because == "expired"


def test_phone_check_runs_on_start_and_then_every_minute():
    calls = []
    client = FakeClient([])
    t = [0.0]
    run_connection(client, "u", "cfat_x", "inst", 150, sleep=lambda s: t.__setitem__(0, t[0] + s),
                   clock=lambda: t[0], log=lambda *_: None, on_session=lambda c, s: calls.append(t[0]),
                   periodic_s=60)
    assert calls == [0.0, 60.0, 120.0]


def test_a_timeout_or_a_5xx_never_stops_the_agent():
    # Staging 2026-10-19: one read timeout closed the Agent mid-job (5/24 clips sent) until someone restarted it.
    errors = [TimeoutError("The read operation timed out"), ServerError(502, "HTTP_ERROR", "Bad Gateway"),
              ServerError(500, "INTERNAL", "x"), OSError("network down")]
    client = FakeClient([None, *errors, None, None])
    logs: list[str] = []
    t = [0.0]
    result = run_connection(client, "u", "cfat_x", "inst", 400, sleep=lambda s: t.__setitem__(0, t[0] + s),
                            clock=lambda: t[0], log=logs.append)
    assert result.stopped_because == "duration_elapsed" and client.auths == 1
    assert sum("ชั่วคราว" in m for m in logs) == 4 and any("ได้อีกครั้ง" in m for m in logs)
    assert result.heartbeats > 3  # back to heartbeats after the outage


def test_a_long_outage_signs_in_again_when_the_session_expired():
    expired = ServerError(401, "AGENT_SESSION_ENDED", "x", {"reason": "expired"})
    client = FakeClient([TimeoutError("t")] * 6 + [expired, None])
    result = _run(client, duration=600)
    assert client.auths == 2 and result.stopped_because == "duration_elapsed"


def test_the_first_sign_in_waits_for_the_network_but_not_for_a_refusal():
    class Flaky(FakeClient):
        def __init__(self, errors):
            super().__init__([])
            self.errors = list(errors)

        def authenticate(self, *a):
            if self.errors:
                raise self.errors.pop(0)
            return super().authenticate(*a)

    client = Flaky([OSError("no route"), ServerError(503, "HTTP_ERROR", "starting")])
    assert _run(client, duration=60).stopped_because == "duration_elapsed" and client.auths == 1
    with pytest.raises(ServerError):
        _run(Flaky([ServerError(401, "AGENT_AUTH_FAILED", "bad token")]))


def test_a_failing_end_call_or_phone_check_does_not_raise():
    class Broken(FakeClient):
        def end(self, session):
            raise TimeoutError("t")

    t = [0.0]

    def phone_check(c, s):
        raise TimeoutError("t")

    result = run_connection(Broken([]), "u", "cfat_x", "inst", 60, sleep=lambda s: t.__setitem__(0, t[0] + s),
                            clock=lambda: t[0], log=lambda *_: None, on_session=phone_check, periodic_s=15)
    assert result.stopped_because == "duration_elapsed"
