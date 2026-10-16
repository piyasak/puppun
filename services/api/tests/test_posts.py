"""P4.3: Agents claim due posts with a per-phone lock, leases and dispatch checks (G4-03, G4-04,
G3-05 at submission). Late posts follow the offline policy instead of firing in a burst (G4-02).

The default app is dry-run, like every running server. A second app in live mode exists only here,
to drive the post-Submit states with simulated Agents (no real posting exists, E-40).
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta

import httpx
from api_test_shop import Shop, Worker, claim, ev, expire, items, schedule, set_times


def test_claim_hands_out_due_posts_one_per_phone_in_dry_run(shop, app):
    series = schedule(shop)
    assert claim(shop.w, [shop.serial]) is None  # nothing due yet
    set_times(app, series["id"], [-1, -1])
    assert claim(shop.w, ["SOMEOTHERPHONE"]) is None  # only phones this Agent can reach
    assert claim(shop.w, ["192.168.1.5:5555"]) is None

    post = claim(shop.w, [shop.serial])
    assert post["state"] == "CLAIMED" and post["posting_mode"] == "dry_run" and post["attempt"] == 1
    assert post["device"] == {"serial": shop.serial, "expected_account": "handle0", "account_check": True}
    assert post["text"]["metadata_version"] == 1 and post["text"]["caption"]
    assert post["clip"]["sha256"] == series["items"][0]["clip_sha256"] and post["clip"]["download_url"]
    # The phone is busy: the second due post waits (Q-05), even though it is due.
    assert claim(shop.w, [shop.serial]) is None

    eid = uuid.uuid4().hex
    assert ev(shop.w, post["id"], "TRANSFERRING", eid).json()["state"] == "TRANSFERRING"
    assert ev(shop.w, post["id"], "TRANSFERRING", eid).json()["duplicate"] is True
    assert ev(shop.w, post["id"], "SUBMITTING").json()["code"] == "BAD_EVENT_ORDER"
    assert ev(shop.w, post["id"], "PREPARING").json()["state"] == "PREPARING"
    refused = ev(shop.w, post["id"], "SUBMITTING")
    assert refused.status_code == 409 and refused.json()["code"] == "POSTING_DISABLED"
    assert ev(shop.w, post["id"], "DRY_RUN_DONE").json()["state"] == "DRY_RUN_DONE"

    second = claim(shop.w, [shop.serial])
    assert second["id"] == series["items"][1]["id"]
    for kind in ("TRANSFERRING", "PREPARING", "DRY_RUN_DONE"):
        ev(shop.w, second["id"], kind)
    done = shop.acc.get(f"/v1/schedules/{series['id']}").json()
    assert done["state"] == "COMPLETED" and done["counts"] == {"DRY_RUN_DONE": 2}
    first = done["items"][0]
    # Plan and reality are kept apart (G4-05).
    assert first["claimed_at"] and first["started_at"] and first["submitted_at"] is None


def two_agents(shop):
    env = shop.env
    shop.acc.patch(f"/v1/environments/{env['id']}", json={"name": env["name"], "registered_agent_limit": 2,
                                                          "concurrent_session_limit": 2, "device_limit": 1})


def test_two_agents_racing_never_get_the_same_post(shop, app, client, server_url):  # G4-03
    two_agents(shop)
    other = Worker(client, shop.acc.username, shop.token)
    assert other.auth().status_code == 200
    series = schedule(shop)
    set_times(app, series["id"], [-2, -1])
    got = []

    def race(worker):
        resp = httpx.post(f"{server_url}/v1/agent/posts/claim", json={"ready_serials": [shop.serial]},
                          headers={"Authorization": f"Bearer {worker.session}"}, timeout=30)
        got.append(resp.json()["post"])

    threads = [threading.Thread(target=race, args=(w,)) for w in (shop.w, other, shop.w, other)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    claimed = [p for p in got if p]
    assert len(claimed) == 1  # one phone, one post at a time, one Agent
    assert sorted(i["state"] for i in items(shop, series["id"])) == ["CLAIMED", "SCHEDULED"]


def test_lost_agent_before_submit_is_redelivered_then_parked(shop, app, client):  # G4-04
    two_agents(shop)
    series = schedule(shop, clips=1)
    set_times(app, series["id"], [-1])
    lost = Worker(client, shop.acc.username, shop.token)  # a second PC that will go silent
    assert lost.auth().status_code == 200
    post = claim(lost, [shop.serial])
    ev(lost, post["id"], "TRANSFERRING")
    expire(app, post["id"])
    again = claim(shop.w, [shop.serial])
    assert again["id"] == post["id"] and again["attempt"] == 2  # nothing was posted: safe to hand out again
    # The first holder's lease is gone: anything it still reports is refused.
    assert ev(lost, post["id"], "PREPARING").json()["code"] == "LEASE_LOST"
    expire(app, post["id"])
    assert claim(shop.w, [shop.serial])["attempt"] == 3
    expire(app, post["id"])
    assert claim(shop.w, [shop.serial]) is None
    item = items(shop, series["id"])[0]
    assert (item["state"], item["reason"]) == ("NEEDS_ACTION", "AGENT_LOST")


def test_failure_before_submit_retries_the_same_slot(shop, app):
    series = schedule(shop, clips=1)
    set_times(app, series["id"], [-1])
    post = claim(shop.w, [shop.serial])
    assert ev(shop.w, post["id"], "RETRYABLE_FAILED", code="TRANSFER_FAILED").json()["state"] == "SCHEDULED"
    post = claim(shop.w, [shop.serial])
    resp = ev(shop.w, post["id"], "NEEDS_ACTION", code="ACCOUNT_MISMATCH", detail="logged in as someone else")
    assert resp.json()["state"] == "NEEDS_ACTION"
    assert items(shop, series["id"])[0]["reason"] == "ACCOUNT_MISMATCH"


def live(shop, live_client):
    w = Worker(live_client, shop.acc.username, shop.token, shop.w.installation_id)  # same PC, new session
    assert w.auth().status_code == 200
    return w


def test_text_changed_while_preparing_is_refused_at_submit(shop, app, live_client):  # G3-05 at submission
    series = schedule(shop, clips=1)
    lw = live(shop, live_client)  # after the job: reconnecting the same PC ends the old session
    set_times(app, series["id"], [-1])
    post = claim(lw, [shop.serial])
    ev(lw, post["id"], "TRANSFERRING")
    ev(lw, post["id"], "PREPARING")
    clip_id = series["items"][0]["clip_id"]
    shop.acc.patch(f"/v1/clips/{clip_id}/metadata", json={"expected_version": 1, "caption": "แก้ระหว่างเตรียมโพสต์"})
    refused = ev(lw, post["id"], "SUBMITTING")
    assert refused.status_code == 409 and refused.json()["code"] == "DISPATCH_REVOKED"
    item = items(shop, series["id"])[0]
    # Review mode: the edited text is not approved yet, so the post must not go out.
    assert (item["state"], item["reason"], item["submitted_at"]) == ("NEEDS_ACTION", "NOT_APPROVED", None)


def test_success_needs_evidence_and_after_submit_nothing_is_retried(shop, app, live_client):
    series = schedule(shop, clips=2)
    lw = live(shop, live_client)  # after the job: reconnecting the same PC ends the old session
    set_times(app, series["id"], [-2, -1])
    post = claim(lw, [shop.serial])
    for kind in ("TRANSFERRING", "PREPARING", "SUBMITTING", "VERIFYING"):
        assert ev(lw, post["id"], kind).status_code == 200
    assert ev(lw, post["id"], "NEEDS_ACTION").json()["code"] == "BAD_EVENT_ORDER"  # must be UNKNOWN or verified
    assert ev(lw, post["id"], "VERIFIED_SUCCESS").json()["code"] == "EVIDENCE_REQUIRED"
    ok = ev(lw, post["id"], "VERIFIED_SUCCESS", evidence={"method": "caption_marker", "value": "cf2143e0",
                                                          "account": "handle0"})
    assert ok.json()["state"] == "VERIFIED_SUCCESS"
    first = items(shop, series["id"])[0]
    assert first["submitted_at"] and first["verified_at"]

    # Second post: the Agent disappears after Submit -> UNKNOWN, never handed out again,
    # and the phone stays blocked until someone resolves it.
    post = claim(lw, [shop.serial])
    for kind in ("TRANSFERRING", "PREPARING", "SUBMITTING"):
        ev(lw, post["id"], kind)
    expire(app, post["id"])
    assert claim(lw, [shop.serial]) is None
    second = items(shop, series["id"])[1]
    assert (second["state"], second["reason"]) == ("UNKNOWN", "AGENT_LOST_AFTER_SUBMIT")


def test_missed_posts_are_deferred_with_their_spacing_not_fired_together(shop, app):  # G4-02
    series = schedule(shop, clips=3, interval_hours=2)
    set_times(app, series["id"], [-300, -180, -60 - 5])  # PC was off: all three missed (> 60 min late)
    post = claim(shop.w, [shop.serial])
    after = items(shop, series["id"])
    assert post["id"] == after[0]["id"]
    times = [datetime.fromisoformat(i["scheduled_at"]) for i in after]
    assert times[1] - times[0] == timedelta(hours=2) and times[2] - times[1] == timedelta(hours=2)
    assert [i["state"] for i in after] == ["CLAIMED", "SCHEDULED", "SCHEDULED"]
    assert claim(shop.w, [shop.serial]) is None  # nothing else fires now


def test_missed_posts_are_skipped_when_the_series_says_so(shop, app):
    series = schedule(shop, clips=3, offline_policy="skip")
    set_times(app, series["id"], [-300, -180, -10])  # two missed, one just due
    post = claim(shop.w, [shop.serial])
    after = items(shop, series["id"])
    assert [i["state"] for i in after] == ["SKIPPED", "SKIPPED", "CLAIMED"] and post["id"] == after[2]["id"]
    assert after[0]["reason"] == "MISSED_SLOT"


def test_released_phone_and_other_environments_get_nothing(shop, app, onboard, client, real_clip):  # noqa: F811
    series = schedule(shop, clips=1)
    set_times(app, series["id"], [-1])
    stranger = Shop(onboard(), client, real_clip)
    assert claim(stranger.w, [shop.serial]) is None
    assert ev(stranger.w, series["items"][0]["id"], "TRANSFERRING").status_code == 404
    shop.acc.post(f"/v1/devices/{shop.devices[0]}/unbind")
    assert claim(shop.w, [shop.serial]) is None


def test_verifying_keeps_its_lease_long_enough_for_a_public_check(shop, app, live_client):
    # tx1, 2026-10-16: fb8f276c's check took over 5 min and the 5-min lease turned it UNKNOWN meanwhile.
    from clipflow_api import posts as post_rules
    from clipflow_api.models import ScheduleItem

    def lease_left(item_id):
        with app.state.db.sessionmaker() as s:
            expires = s.get(ScheduleItem, uuid.UUID(item_id)).lease_expires_at
        return (expires - datetime.now(expires.tzinfo)).total_seconds()

    series = schedule(shop, clips=1)
    lw = live(shop, live_client)
    set_times(app, series["id"], [-1])
    post = claim(lw, [shop.serial])
    for kind in ("TRANSFERRING", "PREPARING", "SUBMITTING"):
        assert ev(lw, post["id"], kind).status_code == 200
    assert lease_left(post["id"]) <= post_rules.LEASE_S
    assert ev(lw, post["id"], "VERIFYING").status_code == 200
    assert lease_left(post["id"]) > post_rules.LEASE_S * 3  # 20 min, not 5
