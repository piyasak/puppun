"""PC of tx1/tx2, 2026-10-15: after a retry the server sent attempt 1 again; the journal already held
f240f595-…-1, TransitionError escaped and the posting thread stopped for every phone."""

from __future__ import annotations

from agent.attempt import State
from agent.post_runner import PostRunner, _Post

POST = {"id": "f240f595-172b-40c3-bcc6-cda52feaf9d0", "attempt": 1, "state": "CLAIMED",
        "device": {"serial": "S"}, "text": {"caption": "x", "hashtags": []}}


def test_an_attempt_number_seen_before_gets_a_new_journal_id(tmp_path):
    runner = PostRunner(tmp_path, adb_factory=lambda: None, log=lambda m: None)
    first = _Post(runner, None, None, POST, None, None)
    assert first.attempt_id == f"{POST['id']}-1"
    runner.journal.begin(first.attempt_id)
    runner.journal.advance(first.attempt_id, State.NEEDS_ACTION, "ACCOUNT_UNREADABLE")
    again = _Post(runner, None, None, POST, None, None)  # retry: the server restarts at attempt 1
    assert again.attempt_id == f"{POST['id']}-1.r2"
    runner.journal.begin(again.attempt_id)  # no TransitionError
    assert runner.journal.current(first.attempt_id) == State.NEEDS_ACTION  # the old record stays
    assert _Post(runner, None, None, POST, None, None).attempt_id == f"{POST['id']}-1.r3"


def test_an_unexpected_error_does_not_stop_posting(tmp_path):
    logs = []
    runner = PostRunner(tmp_path, adb_factory=lambda: None, log=logs.append, poll_s=0)
    calls = []

    def run_once(client, get_session):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        runner._halt.set()
        return None

    runner.run_once = run_once
    runner.delete_posted_clips = lambda client, get_session: None
    runner._loop(None, None)
    assert len(calls) == 2 and any("RuntimeError" in m for m in logs)
