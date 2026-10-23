"""Posts on several phones at once (0.10.0, PO 2026-10-23): settable, default 1, same-time starts 30-90 s apart."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from agent.adb import normalize_serial
from agent.attempt import AttemptJournal, State
from agent.credentials import parallel_posts
from agent.post_runner import PostRunner


@dataclass
class Phone:
    hw_serial: str
    adb_serial: str
    state: str = "device"


PHONES = {s: Phone(s, f"adb-{s}") for s in ("TX1", "TX2", "TX3")}


class Client:
    """Every phone has a post due; a claim returns one for the first serial it is offered."""

    def __init__(self):
        self.offered: list[list[str]] = []
        self.diagnostics: list[list[str]] = []

    def claim_post(self, session, serials):
        self.offered.append(list(serials))
        return {"id": f"post-{serials[0]}", "device": {"serial": serials[0], "display_name": serials[0].lower()}}

    def diagnostic_requested(self, session, serials):
        self.diagnostics.append(list(serials))
        return None


def runner(tmp_path, n, logs=None, stagger=(30.0, 90.0)):
    r = PostRunner(tmp_path, adb_factory=lambda: None, log=(logs.append if logs is not None else lambda m: None),
                   max_parallel=n, stagger_s=stagger)
    r._ready_phones = lambda adb: {normalize_serial(k): p for k, p in PHONES.items()}  # as discover() gives them
    release = threading.Event()
    running: list[str] = []
    peak = [0]
    lock = threading.Lock()

    def execute(client, get_session, post, adb, phone):
        with lock:
            running.append(phone.hw_serial)
            peak[0] = max(peak[0], len(running))
        r.log(f"posting {post['id']}")
        release.wait(5)
        with lock:
            running.remove(phone.hw_serial)
        if phone.hw_serial == "TX2":
            raise RuntimeError("phone fell off the USB")
        return "VERIFIED_SUCCESS"

    r._execute = execute
    return r, release, peak


def wait_idle(r):
    for _ in range(200):
        if not r.active():
            return
        time.sleep(0.01)
    raise AssertionError("still busy")


def test_default_is_one_phone_at_a_time(tmp_path):
    r, release, peak = runner(tmp_path, 1)
    client = Client()
    assert r.dispatch_once(client, lambda: None) is True
    assert r.dispatch_once(client, lambda: None) is False  # the slot is taken: nothing else starts
    assert len(client.offered) == 1
    release.set()
    wait_idle(r)
    assert peak[0] == 1


def test_several_phones_each_once_and_same_time_starts_wait_30_to_90_s(tmp_path):
    logs: list[str] = []
    r, release, peak = runner(tmp_path, 3, logs)
    client = Client()
    assert r.dispatch_once(client, lambda: None) is True  # TX1 starts at once
    wait = r._next_start - time.monotonic()
    assert 29 <= wait <= 90
    assert r.dispatch_once(client, lambda: None) is False  # TX2 waits for the stagger
    r._next_start = 0.0  # the wait has passed
    assert r.dispatch_once(client, lambda: None) is True
    assert client.offered[1] == ["TX2", "TX3"]  # a busy phone is never offered again
    r._next_start = 0.0
    assert r.dispatch_once(client, lambda: None) is True
    r._next_start = 0.0
    assert r.dispatch_once(client, lambda: None) is False  # 3 of 3 busy
    release.set()
    wait_idle(r)
    assert peak[0] == 3
    # TX2 failed in its own thread: logged, the others finished, and its slot is free again
    assert any("RuntimeError" in m and m.startswith("[tx2]") for m in logs)
    assert any(m.startswith("[tx1] posting") for m in logs) and any(m.startswith("[tx3] posting") for m in logs)


def test_nothing_due_lets_a_free_phone_take_a_screen_check(tmp_path):
    r, release, _ = runner(tmp_path, 2)
    client = Client()
    assert r.dispatch_once(client, lambda: None) is True  # TX1 posting
    client.claim_post = lambda session, serials: None
    r._next_start = 0.0
    r.dispatch_once(client, lambda: None)
    assert client.diagnostics[-1] == ["TX2", "TX3"]  # never the phone that is posting
    release.set()
    wait_idle(r)


def test_the_journal_takes_writes_from_many_phones_at_once(tmp_path):
    journal = AttemptJournal(tmp_path / "attempts.jsonl")
    ids = [f"0000000{i}-0000-4000-8000-00000000000{i}-1" for i in range(6)]

    def post(attempt_id):
        same_file = AttemptJournal(tmp_path / "attempts.jsonl")  # each post may hold its own instance
        same_file.begin(attempt_id)
        for state in (State.TRANSFERRING, State.PREPARING, State.SUBMITTING, State.VERIFYING, State.VERIFIED_SUCCESS):
            same_file.advance(attempt_id, state)

    threads = [threading.Thread(target=post, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(journal.current(i) == State.VERIFIED_SUCCESS for i in ids)
    assert len((tmp_path / "attempts.jsonl").read_text(encoding="utf-8").splitlines()) == 6 * 6


def test_the_setting_is_1_to_10_and_anything_odd_is_1():
    assert [parallel_posts(v) for v in (None, "x", 0, -2, 1, 3, "4", 99)] == [1, 1, 1, 1, 1, 3, 4, 10]
