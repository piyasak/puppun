"""Post now (PO 2026-10-10): one approved clip, due now on a chosen phone, through every check of a
scheduled post. Posting mode stays the server's (dry-run here)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from api_test_shop import claim


def post_now(shop, clip_id, key=None, device=None):
    return shop.acc.post(f"/v1/clips/{clip_id}/post-now",
                         json={"device_id": device or shop.devices[0], "idempotency_key": key or uuid.uuid4().hex})


def test_post_now_makes_one_post_due_now_that_the_agent_takes(shop):
    _, clips = shop.job(clips=3, approve=3)
    made = post_now(shop, clips[1])
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["posting_mode"] == "dry_run" and len(body["items"]) == 1
    item = body["items"][0]
    assert item["clip_id"] == clips[1] and item["state"] == "SCHEDULED"
    due = datetime.fromisoformat(item["scheduled_at"])
    assert abs(due - datetime.now(UTC)) < timedelta(minutes=2)  # now, by the server's clock
    post = claim(shop.w, [shop.serial])
    assert post is not None and post["id"] == item["id"]  # the Agent takes it on its next poll


def test_post_now_keeps_the_rules_of_a_scheduled_post(shop, onboard):
    _, clips = shop.job(clips=2, approve=1)
    key = uuid.uuid4().hex
    first = post_now(shop, clips[0], key)
    assert first.status_code == 201
    assert post_now(shop, clips[0], key).status_code == 201  # same key: the same post, not a second one
    again = post_now(shop, clips[0])
    assert again.status_code == 409 and again.json()["details"]["excluded"][0]["reason"] == "ALREADY_SCHEDULED"
    unapproved = post_now(shop, clips[1])
    assert unapproved.status_code == 409 and unapproved.json()["details"]["excluded"][0]["reason"] == "NOT_APPROVED"
    assert onboard().post(f"/v1/clips/{clips[0]}/post-now",
                          json={"device_id": shop.devices[0], "idempotency_key": uuid.uuid4().hex}).status_code == 404


def test_schedule_can_take_only_some_clips(shop):
    job_id, clips = shop.job(clips=3, approve=3)
    series = shop.create(job_id, clip_ids=[clips[0], clips[2]], window_start="00:00", window_end="24:00").json()
    assert [i["clip_id"] for i in series["items"]] == [clips[0], clips[2]]


def test_a_post_that_stopped_for_a_person_says_so_and_can_be_cancelled_first(shop):
    """QA 2026-10-11: a post stopped with ACCOUNT_UNREADABLE; "post now" on the same clip said only
    "no approved clips". It now says why, and works once the stopped post is cancelled."""
    from api_test_shop import ev

    _, clips = shop.job(clips=1, approve=1)
    item = post_now(shop, clips[0]).json()["items"][0]
    post = claim(shop.w, [shop.serial])
    assert ev(shop.w, post["id"], "TRANSFERRING").status_code == 200
    stopped = ev(shop.w, post["id"], "NEEDS_ACTION", code="ACCOUNT_UNREADABLE")
    assert stopped.status_code == 200
    again = post_now(shop, clips[0])
    assert again.status_code == 409
    assert again.json()["details"]["excluded"][0]["reason"] == "POST_NEEDS_ACTION"
    assert "ต้องดำเนินการค้างอยู่" in again.json()["message"]
    listed = shop.acc.get(f"/v1/schedules/{item['series_id']}").json()["items"][0]
    assert listed["state"] == "NEEDS_ACTION" and listed["reason"] == "ACCOUNT_UNREADABLE"
    cancel = shop.acc.post(f"/v1/schedule-items/{item['id']}/cancel",
                           json={"expected_state_version": listed["state_version"]})
    assert cancel.status_code == 200, cancel.text
    assert post_now(shop, clips[0]).status_code == 201
