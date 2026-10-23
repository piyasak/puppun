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

    def dispatch_once(client, get_session):  # 0.10.0: the loop starts work through the dispatcher
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        runner._halt.set()
        return False

    runner.dispatch_once = dispatch_once
    runner.delete_posted_clips = lambda client, get_session: None
    runner._loop(None, None)
    assert len(calls) == 2 and any("RuntimeError" in m for m in logs)


class Server:
    def __init__(self, states):
        self.states, self.asked = states, []

    def post_state(self, session, post_id):
        self.asked.append(post_id)
        return self.states[post_id]


def test_on_start_records_the_server_has_settled_are_settled_and_the_rest_wait(tmp_path):
    # 2026-10-15: 5b3b367d-…-1 stayed SUBMITTING here after a person resolved it; every update was refused.
    from agent import updater

    runner = PostRunner(tmp_path, adb_factory=lambda: None, log=lambda m: None)
    resolved, waiting, early = (f"{p}-1" for p in ("5b3b367d-e1fb-46b5-b498-713d299e473b",
                                                   "aaaaaaaa-0000-4000-8000-000000000001",
                                                   "bbbbbbbb-0000-4000-8000-000000000002"))
    for attempt_id, upto in ((resolved, State.SUBMITTING), (waiting, State.VERIFYING), (early, State.PREPARING)):
        runner.journal.begin(attempt_id)
        for step in (State.TRANSFERRING, State.PREPARING, State.SUBMITTING, State.VERIFYING):
            runner.journal.advance(attempt_id, step)
            if step == upto:
                break
    assert len(updater.posts_in_flight(tmp_path)) == 2
    server = Server({"5b3b367d-e1fb-46b5-b498-713d299e473b": {"state": "CLAIMED", "attempt": 2},
                     "aaaaaaaa-0000-4000-8000-000000000001": {"state": "VERIFYING", "attempt": 1}})
    assert runner.settle_journal(server, lambda: None) == [resolved]
    assert runner.journal.current(resolved) == State.UNKNOWN
    assert runner.journal.current(waiting) == State.VERIFYING  # the server still waits: a person decides
    assert runner.journal.current(early) == State.RETRYABLE_FAILED  # stopped before Submit: nothing posted
    assert updater.posts_in_flight(tmp_path) == [waiting]
