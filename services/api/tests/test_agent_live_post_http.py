"""The posting path after Submit (P5.4/P5.5, G5-04) with a simulated phone and TikTok UI against a
live-mode test server. No real post happens here; the authorized real one is test_authorized_real_post.py.
"""

from __future__ import annotations

import json
import uuid

import pytest
from api_test_shop import FULL_DAY, expire, items, set_times
from test_agent_post_runner_http import FakePhone

from agent import authorization
from agent.adb import Adb
from agent.post_runner import PostRunner
from agent.server_client import ServerClient
from agent.tiktok_ui import UiStop


class Gallery(FakePhone):
    def run(self, args):
        if len(args) > 3 and args[3].startswith("content query") and "_display_name='" not in args[3]:
            return "".join(f"Row: {i} _id={60 + i}, _display_name={p.rsplit('/', 1)[-1]}\n"
                           for i, p in enumerate(self.files))
        return super().run(args)


class PostingUi:
    def __init__(self, verify_fails=False, during=None):
        self.verify_fails, self.calls, self.posted, self.during = verify_fails, [], 0, during

    def check_account(self, expected):
        self.calls.append("account")
        if self.during:
            self.during()
        return expected

    def private_count(self):
        return 1 + self.posted

    def open_post_screen(self, media_id):
        self.calls.append("open")

    def set_only_me(self):
        self.calls.append("only_me")

    def type_caption(self, caption):
        self.calls.append("caption")
        self.caption = caption

    def submit(self, grant, caption):
        assert isinstance(grant, authorization.PostGrant)
        self.posted += 1
        self.calls.append("POST")

    def verify_private_post(self, marker, before):
        if self.verify_fails:
            raise UiStop("VERIFY_MARKER", "marker not found")
        assert marker in self.caption and self.private_count() == before + 1
        return {"method": "caption_marker", "value": marker, "account": "handle0", "private_before": before,
                "private_after": before + 1}

    def close(self):
        self.calls.append("close")


@pytest.fixture
def live(shop, app, live_server_url, server_url, tmp_path):  # server_url serves the download links
    env = shop.env  # the posting PC is a second Agent, so the clip-making Agent keeps its session
    shop.acc.patch(f"/v1/environments/{env['id']}", json={"name": env["name"], "registered_agent_limit": 2,
                                                          "concurrent_session_limit": 2, "device_limit": 1})
    client = ServerClient(live_server_url)
    session = client.authenticate(shop.acc.username, shop.token, str(uuid.uuid4()))

    def make(ui, *, crash=False, allowed=1):
        job_id, _ = shop.job(clips=1)
        series = shop.create(job_id, **FULL_DAY).json()
        set_times(app, series["id"], [-1])
        data_dir = tmp_path / "agent-data"
        phone = Gallery(shop.serial)
        ledger = data_dir / "authorizations.json"
        runner = PostRunner(data_dir, lambda: Adb(phone.run), log=lambda *_: None, retry_wait_s=0.1,
                            ui_factory=lambda adb, serial: ui, crash_after_submit=crash,
                            grant_source=lambda note: authorization.take(ledger, "Q-TEST", allowed, note))
        return {"series": series, "run": lambda: runner.run_once(client, lambda: session), "ledger": ledger,
                "data_dir": data_dir, "client": client, "session": session}
    return make


def test_live_post_is_verified_with_evidence(shop, live):
    ui = PostingUi()
    s = live(ui)
    assert s["run"]() == "VERIFIED_SUCCESS"
    assert ui.calls == ["account", "open", "only_me", "caption", "POST", "close"]
    item = items(shop, s["series"]["id"])[0]
    assert item["state"] == "VERIFIED_SUCCESS" and item["submitted_at"] and item["verified_at"]
    assert item["evidence"]["method"] == "caption_marker" and item["evidence"]["value"].startswith("cf")
    assert json.loads(s["ledger"].read_text(encoding="utf-8"))["Q-TEST"]["allowed"] == 1


def test_a_used_grant_never_posts_again(shop, live):
    ui = PostingUi()
    s = live(ui)
    assert s["run"]() == "VERIFIED_SUCCESS"
    second = PostingUi()
    s2 = live(second)  # same ledger file (same tmp_path), the one post is used
    assert s2["run"]() == "SCHEDULED"  # refused before Submit: retryable, nothing pressed
    assert "POST" not in second.calls
    assert items(shop, s2["series"]["id"])[0]["reason"] == "NO_GRANT"


def test_crash_right_after_post_becomes_unknown_and_is_not_retried(shop, app, live):  # G5-04
    ui = PostingUi()
    s = live(ui, crash=True)
    assert s["run"]() == "crashed"
    item = items(shop, s["series"]["id"])[0]
    assert item["state"] == "SUBMITTING"
    expire(app, item["id"])
    assert s["client"].claim_post(s["session"], [shop.serial]) is None  # the phone is held, nothing replayed
    after = items(shop, s["series"]["id"])[0]
    assert (after["state"], after["reason"]) == ("UNKNOWN", "AGENT_LOST_AFTER_SUBMIT")
    lines = [json.loads(x)["state"] for x in (s["data_dir"] / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines[-1] == "SUBMITTING"  # the local journal agrees: recover() turns it into UNKNOWN
    assert ui.posted == 1


def test_verification_that_fails_after_post_is_unknown_not_a_retry(shop, live):
    ui = PostingUi(verify_fails=True)
    s = live(ui)
    assert s["run"]() == "UNKNOWN"
    item = items(shop, s["series"]["id"])[0]
    assert (item["state"], item["reason"]) == ("UNKNOWN", "VERIFY_MARKER") and ui.posted == 1


def test_a_session_lost_during_the_tiktok_steps_does_not_spend_the_grant(shop, live):
    """QA run 2026-10-08: the session expired while TikTok was being driven; the grant was spent and
    the server then refused Submit. Now the session is checked before the grant is touched."""
    holder = {}
    ui = PostingUi(during=lambda: holder["s"]["client"].end(holder["s"]["session"]))
    s = holder["s"] = live(ui)
    assert s["run"]() == "stopped"
    assert "POST" not in ui.calls and not s["ledger"].exists()
