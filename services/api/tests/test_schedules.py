"""P4.1/P4.2 + G3-05: server-calculated schedules bound to approved clip versions.

G4-01 slot math has its own unit tests (tests/unit/test_slots.py); these run the same rules
through the API on Postgres, with real 1080x1920 clips so approval follows the real checks.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from test_clips import Worker, real_clip  # noqa: F401 - real_clip is a fixture

from clipflow_api import schedules
from clipflow_api.models import ScheduleItem

URL = "https://www.bilibili.tv/en/video/4800844531374592"
BKK = ZoneInfo("Asia/Bangkok")
TOMORROW = (datetime.now(BKK) + timedelta(days=1)).strftime("%Y-%m-%d")


class Shop:
    def __init__(self, acc, client, clip_bytes, devices=1):
        self.acc, self.clip_bytes = acc, clip_bytes
        self.env = acc.post("/v1/environments", json={"name": f"office-{uuid.uuid4().hex[:6]}",
                                                      "device_limit": devices}).json()
        token = acc.post("/v1/agent-tokens", json={"environment_id": self.env["id"], "name": "pc"}).json()["token"]
        self.w = Worker(client, acc.username, token)
        assert self.w.auth().status_code == 200
        self.devices = [self.phone(f"handle{i}") for i in range(devices)]

    def phone(self, account):
        serial = f"SCH{uuid.uuid4().hex[:10].upper()}"
        dev = self.w.post("/v1/agent/devices/register", json={"serial": serial, "adb_state": "device",
                                                               "model": "25078PC3EG", "android_version": "15"}).json()
        if account:
            self.acc.patch(f"/v1/devices/{dev['id']}", json={"display_name": "POCO", "expected_account": account})
        return dev["id"]

    def job(self, clips=3, approve=3, mode="review"):
        body = {"idempotency_key": uuid.uuid4().hex, "environment_id": self.env["id"], "requested_clips": clips,
                "source": {"kind": "url", "url": URL}, "clip_min_s": 15, "clip_max_s": 20, "review_mode": mode}
        if mode == "auto":
            body["confirm_auto"] = True
        job_id = self.acc.post("/v1/jobs", json=body).json()["id"]
        self.w.post("/v1/agent/jobs/claim")
        self.w.event(job_id, "source_validated", duration_s=600, possible_clips=clips)
        self.w.event(job_id, "stage", stage="RENDERING")
        for i in range(1, clips + 1):
            assert self.w.report(job_id, i, self.clip_bytes).status_code == 200
            assert self.w.upload(job_id, i, self.clip_bytes).status_code == 200
        self.w.event(job_id, "completed")
        clips_out = self.acc.get(f"/v1/jobs/{job_id}").json()["clips"]
        if mode == "review":
            for c in clips_out[:approve]:
                assert self.acc.post(f"/v1/clips/{c['id']}/approve", json={"metadata_version": 1}).status_code == 200
        return job_id, [c["id"] for c in clips_out]

    def body(self, job_id, device=None, **kw):
        return {"job_id": job_id, "device_id": device or self.devices[0], "start_local": f"{TOMORROW}T19:00",
                "interval_hours": 2, "window_start": "09:00", "window_end": "21:00"} | kw

    def preview(self, job_id, **kw):
        return self.acc.post("/v1/schedules/preview", json=self.body(job_id, **kw))

    def create(self, job_id, key=None, **kw):
        return self.acc.post("/v1/schedules", json=self.body(job_id, **kw) | {"idempotency_key": key or uuid.uuid4().hex})


@pytest.fixture
def shop(onboard, client, real_clip):  # noqa: F811
    return Shop(onboard(), client, real_clip)


def day_after(date: str) -> str:
    return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")


def test_preview_follows_the_prd_rules_and_saves_nothing(shop):  # G4-01 / T11 through the API
    job_id, _ = shop.job()
    resp = shop.preview(job_id)
    assert resp.status_code == 200, resp.text
    p = resp.json()
    nxt = day_after(TOMORROW)
    assert [i["scheduled_local"] for i in p["items"]] == [f"{TOMORROW}T19:00", f"{nxt}T09:00", f"{nxt}T11:00"]
    assert p["window"] == "09:00–21:00" and p["timezone"] == "Asia/Bangkok" and p["excluded"] == []
    assert [i["clip_index"] for i in p["items"]] == [1, 2, 3]
    assert shop.acc.get("/v1/schedules").json()["items"] == []


def test_only_approved_clips_are_scheduled(shop):  # G3-05
    job_id, clip_ids = shop.job(approve=2)
    p = shop.preview(job_id).json()
    assert [i["clip_index"] for i in p["items"]] == [1, 2]
    assert p["excluded"] == [{"clip_id": clip_ids[2], "index": 3, "reason": "NOT_APPROVED"}]

    none_job, _ = shop.job(approve=0)
    resp = shop.preview(none_job)
    assert resp.status_code == 409 and resp.json()["code"] == "NO_APPROVED_CLIPS"


def test_create_binds_the_approved_version_and_is_idempotent(shop):
    job_id, clip_ids = shop.job()
    key = uuid.uuid4().hex
    first = shop.create(job_id, key=key)
    assert first.status_code == 201, first.text
    series = first.json()
    assert series["state"] == "ACTIVE" and series["counts"] == {"SCHEDULED": 3}
    item = series["items"][0]
    clip = shop.acc.get(f"/v1/clips/{clip_ids[0]}").json()
    assert item["metadata_version"] == 1 and item["clip_sha256"] == clip["render_sha256"]
    assert item["claimed_at"] is None and item["verified_at"] is None  # plan and outcome kept apart
    again = shop.create(job_id, key=key)
    assert again.status_code == 200 and again.json()["id"] == series["id"]
    # The same clips cannot go into a second live series (never posted twice, G4-02).
    dup = shop.create(job_id)
    assert dup.status_code == 409 and dup.json()["code"] == "NO_APPROVED_CLIPS"
    assert {e["reason"] for e in dup.json()["details"]["excluded"]} == {"ALREADY_SCHEDULED"}


def test_editing_text_after_scheduling_stops_the_post_until_approved_again(shop, app):  # G3-05
    job_id, clip_ids = shop.job(clips=1, approve=1)
    item = shop.create(job_id).json()["items"][0]
    edited = shop.acc.patch(f"/v1/clips/{clip_ids[0]}/metadata", json={"expected_version": 1, "caption": "ใหม่"})
    assert edited.status_code == 200
    parked = shop.acc.get(f"/v1/schedules/{item['series_id']}").json()["items"][0]
    assert (parked["state"], parked["reason"], parked["metadata_version"]) == ("NEEDS_ACTION", "APPROVAL_CHANGED", 1)
    with app.state.db.sessionmaker() as s:
        assert schedules.dispatchable(s, s.get(ScheduleItem, uuid.UUID(item["id"]))) == "NOT_SCHEDULED"

    # The owner approves the new text: the item now names version 2 and may run again.
    shop.acc.post(f"/v1/clips/{clip_ids[0]}/approve", json={"metadata_version": 2})
    rebound = shop.acc.get(f"/v1/schedules/{item['series_id']}").json()["items"][0]
    assert (rebound["state"], rebound["metadata_version"]) == ("SCHEDULED", 2)
    with app.state.db.sessionmaker() as s:
        assert schedules.dispatchable(s, s.get(ScheduleItem, uuid.UUID(item["id"]))) is None

    shop.acc.post(f"/v1/clips/{clip_ids[0]}/unapprove")
    again = shop.acc.get(f"/v1/schedules/{item['series_id']}").json()["items"][0]
    assert (again["state"], again["reason"]) == ("NEEDS_ACTION", "APPROVAL_CHANGED")


def test_dispatch_check_refuses_a_version_the_item_was_not_scheduled_with(shop, app):  # G3-05
    """Even if an item's state were stale, the last check before dispatch compares versions."""
    job_id, clip_ids = shop.job(clips=1, approve=1)
    item_id = uuid.UUID(shop.create(job_id).json()["items"][0]["id"])
    with app.state.db.sessionmaker() as s:
        item = s.get(ScheduleItem, item_id)
        item.metadata_version = 7  # simulate a binding that no longer matches the approval
        assert schedules.dispatchable(s, item) == "APPROVAL_CHANGED"
        s.rollback()
    shop.acc.post(f"/v1/jobs/{job_id}/cancel")  # finished job: cancel refused, approval stays
    with app.state.db.sessionmaker() as s:
        assert schedules.dispatchable(s, s.get(ScheduleItem, item_id)) is None


def test_auto_mode_rebinds_to_the_auto_approved_new_version(shop):
    job_id, clip_ids = shop.job(clips=1, mode="auto")
    item = shop.create(job_id).json()["items"][0]
    shop.acc.patch(f"/v1/clips/{clip_ids[0]}/metadata", json={"expected_version": 1, "caption": "ใหม่"})
    after = shop.acc.get(f"/v1/schedules/{item['series_id']}").json()["items"][0]
    assert (after["state"], after["metadata_version"]) == ("SCHEDULED", 2)


def test_same_phone_same_time_is_queued_not_refused(shop):  # Q-05, T13 preview
    first_job, _ = shop.job(clips=1)
    assert shop.create(first_job).status_code == 201
    second_job, _ = shop.job(clips=1)
    p = shop.preview(second_job).json()
    item = p["items"][0]
    assert p["collisions"] == 1 and len(item["collides_with"]) == 1
    assert item["scheduled_local"] == f"{TOMORROW}T19:00" and item["expected_start_local"] == f"{TOMORROW}T19:15"
    assert shop.create(second_job).status_code == 201


@pytest.mark.parametrize("change, code", [
    ({"start_local": "2020-01-01T10:00"}, "START_IN_PAST"),
    ({"window_start": "21:00", "window_end": "09:00"}, "WINDOW_INVALID"),
    ({"timezone": "Europe/London"}, "TIMEZONE_UNSUPPORTED"),
])
def test_invalid_requests_are_refused(shop, change, code):
    job_id, _ = shop.job(clips=1)
    resp = shop.preview(job_id, **change)
    assert resp.status_code == 422 and resp.json()["code"] == code


def test_phone_must_be_ready_for_posting(shop, onboard, client, real_clip):  # noqa: F811
    job_id, _ = shop.job(clips=1)
    other_env = Shop(shop.acc, client, real_clip)  # same owner, another Environment
    resp = shop.preview(job_id, device=other_env.devices[0])
    assert resp.json()["code"] == "DEVICE_OTHER_ENVIRONMENT"
    shop.acc.patch(f"/v1/environments/{shop.env['id']}", json={"name": shop.env["name"], "device_limit": 2,
                                                               "registered_agent_limit": 1,
                                                               "concurrent_session_limit": 1})
    no_account = shop.phone(None)
    assert shop.preview(job_id, device=no_account).json()["code"] == "DEVICE_NEEDS_DETAILS"
    stranger = onboard()
    assert stranger.post("/v1/schedules/preview", json=shop.body(job_id)).status_code == 404


def test_cancel_series_and_items(shop):
    job_id, _ = shop.job()
    series = shop.create(job_id).json()
    one = shop.acc.post(f"/v1/schedule-items/{series['items'][0]['id']}/cancel")
    assert one.status_code == 200 and one.json()["state"] == "CANCELLED"
    done = shop.acc.post(f"/v1/schedules/{series['id']}/cancel").json()
    assert done["state"] == "CANCELLED" and done["counts"] == {"CANCELLED": 3}
    assert shop.acc.post(f"/v1/schedules/{series['id']}/cancel").json()["code"] == "SERIES_NOT_ACTIVE"
    # Cancelled clips can be scheduled again.
    assert shop.create(job_id).status_code == 201


def test_unbinding_the_phone_parks_its_posts(shop):
    job_id, _ = shop.job(clips=1)
    series = shop.create(job_id).json()
    shop.acc.post(f"/v1/devices/{shop.devices[0]}/unbind")
    item = shop.acc.get(f"/v1/schedules/{series['id']}").json()["items"][0]
    assert (item["state"], item["reason"]) == ("NEEDS_ACTION", "DEVICE_UNBOUND")


def test_other_workspaces_cannot_see_or_cancel(shop, onboard):
    job_id, _ = shop.job(clips=1)
    series = shop.create(job_id).json()
    stranger = onboard()
    assert stranger.get(f"/v1/schedules/{series['id']}").status_code == 404
    assert stranger.post(f"/v1/schedules/{series['id']}/cancel").status_code == 404
    assert stranger.post(f"/v1/schedule-items/{series['items'][0]['id']}/cancel").status_code == 404
    assert stranger.get("/v1/schedules").json()["items"] == []


def test_two_phones_racing_for_the_same_clips(onboard, client, real_clip, server_url):  # noqa: F811
    shop = Shop(onboard(), client, real_clip, devices=2)
    job_id, _ = shop.job(clips=2)
    results = []

    def create(device):
        body = shop.body(job_id, device=device) | {"idempotency_key": uuid.uuid4().hex}
        results.append(httpx.post(f"{server_url}/v1/schedules", json=body, headers=shop.acc.headers(), timeout=30))

    threads = [threading.Thread(target=create, args=(d,)) for d in shop.devices]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409], [r.text for r in results]
    scheduled = [i for r in results if r.status_code == 201 for i in r.json()["items"]]
    assert len(scheduled) == 2  # each clip exactly once
