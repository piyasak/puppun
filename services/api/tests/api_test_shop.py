"""Shared test helpers: a simulated Agent that makes clips, a shop with phones and approved clips,
and the posting/schedule helpers used by the P3/P4 tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from api_test_agents import Agent
from sqlalchemy import select, update

from clipflow_api.models import ScheduleItem

URL = "https://www.bilibili.tv/en/video/4800844531374592"
BKK = ZoneInfo("Asia/Bangkok")
TOMORROW = (datetime.now(BKK) + timedelta(days=1)).strftime("%Y-%m-%d")
FULL_DAY = {"window_start": "00:00", "window_end": "24:00"}


class Worker(Agent):
    def event(self, job_id, type_, **payload):
        return self.post(f"/v1/agent/jobs/{job_id}/events", json={"event_id": uuid.uuid4().hex, "type": type_, **payload})

    def upload(self, job_id, index, body):
        return self.client.put(f"/v1/agent/jobs/{job_id}/clips/{index}/file", content=body,
                               headers={"Authorization": f"Bearer {self.session}"})

    def prepare(self, job_id, possible=3):
        self.post("/v1/agent/jobs/claim")
        self.event(job_id, "source_validated", duration_s=600, possible_clips=possible)
        for stage in ("DOWNLOADING", "ANALYZING", "RENDERING"):
            self.event(job_id, "stage", stage=stage)

    def report(self, job_id, index, body, duration_ms=16_000, **extra):
        return self.event(job_id, "clip_rendered", index=index, start_ms=0, end_ms=duration_ms,
                          duration_ms=duration_ms, sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body),
                          template_version="tpl-default-v2", title="ชื่อคลิปในวิดีโอ", **extra)


class Shop:
    def __init__(self, acc, client, clip_bytes, devices=1):
        self.acc, self.clip_bytes = acc, clip_bytes
        self.env = acc.post("/v1/environments", json={"name": f"office-{uuid.uuid4().hex[:6]}",
                                                      "device_limit": devices}).json()
        token = self.token = acc.post("/v1/agent-tokens", json={"environment_id": self.env["id"], "name": "pc"}).json()["token"]
        self.w = Worker(client, acc.username, token)
        assert self.w.auth().status_code == 200
        self.devices = [self.phone(f"handle{i}") for i in range(devices)]
        self.serial = acc.get("/v1/devices").json()["items"][0]["serial"] if devices else None

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


def schedule(shop, clips=2, **kw):
    job_id, _ = shop.job(clips=clips)
    resp = shop.create(job_id, **(FULL_DAY | kw))
    assert resp.status_code == 201, resp.text
    return resp.json()


def set_times(app, series_id, offsets):
    """Move a series' items to now + offset (minutes), in seq order."""
    at = datetime.now(UTC)
    with app.state.db.sessionmaker() as s:
        items = s.scalars(select(ScheduleItem).where(ScheduleItem.series_id == uuid.UUID(series_id))
                          .order_by(ScheduleItem.seq)).all()
        for item, minutes in zip(items, offsets, strict=True):
            item.scheduled_at = at + timedelta(minutes=minutes)
        s.commit()


def expire(app, item_id):
    with app.state.db.sessionmaker() as s:
        s.execute(update(ScheduleItem).where(ScheduleItem.id == uuid.UUID(item_id))
                  .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()


def claim(worker, serials):
    resp = worker.post("/v1/agent/posts/claim", json={"ready_serials": serials})
    assert resp.status_code == 200, resp.text
    return resp.json()["post"]


def ev(worker, item_id, type_, event_id=None, **payload):
    return worker.post(f"/v1/agent/posts/{item_id}/events",
                       json={"event_id": event_id or uuid.uuid4().hex, "type": type_, **payload})


def items(shop, series_id):
    return shop.acc.get(f"/v1/schedules/{series_id}").json()["items"]
