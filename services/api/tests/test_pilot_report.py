"""Pilot report (G7-01/G7-02): onboarding minutes and job/post outcomes, with nothing dropped.
Records are moved to a private window in the past so other tests' rows do not count."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from api_test_shop import FULL_DAY
from sqlalchemy import update

from clipflow_api import manage, pilot
from clipflow_api.models import AgentInstallation, Device, Job, ScheduleItem, Workspace


def test_pilot_report_counts_onboarding_and_outcomes(shop, onboard, app):
    t0 = datetime(2001, 1, 1, tzinfo=UTC) + timedelta(days=random.randrange(3000))  # this test's window
    ws = uuid.UUID(shop.acc.body["workspace"]["id"])
    job_id, _ = shop.job(clips=3)
    series = shop.create(job_id, **FULL_DAY).json()
    late = onboard()  # signs up, never starts
    failed_job = shop.acc.post("/v1/jobs", json={
        "idempotency_key": uuid.uuid4().hex, "environment_id": shop.env["id"], "requested_clips": 1,
        "source": {"kind": "url", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        "clip_min_s": 15, "clip_max_s": 20, "review_mode": "review"}).json()["id"]

    with app.state.db.sessionmaker() as s:
        s.execute(update(Workspace).where(Workspace.id == ws).values(created_at=t0))
        s.execute(update(AgentInstallation).where(AgentInstallation.workspace_id == ws).values(created_at=t0 + timedelta(minutes=6)))
        s.execute(update(Device).where(Device.workspace_id == ws).values(created_at=t0 + timedelta(minutes=9)))
        s.execute(update(Job).where(Job.id == uuid.UUID(job_id)).values(created_at=t0 + timedelta(minutes=14)))
        s.execute(update(Job).where(Job.id == uuid.UUID(failed_job)).values(created_at=t0 + timedelta(minutes=30), state="FAILED"))
        s.execute(update(Workspace).where(Workspace.id == uuid.UUID(late.body["workspace"]["id"]))
                  .values(created_at=t0 + timedelta(hours=1)))
        ids = [uuid.UUID(i["id"]) for i in series["items"]]
        for item_id, state, minutes in zip(ids, ["VERIFIED_SUCCESS", "UNKNOWN", "DRY_RUN_DONE"], [60, 120, 180], strict=True):
            s.execute(update(ScheduleItem).where(ScheduleItem.id == item_id)
                      .values(state=state, scheduled_at=t0 + timedelta(minutes=minutes)))
        s.commit()
        out = pilot.report(s, t0, t0 + timedelta(days=1))

    onb = out["onboarding"]
    assert onb["new_workspaces"] == 2 and onb["started"] == 1 and onb["started_pct"] == 50.0
    mine = next(w for w in onb["workspaces"] if w["workspace_id"] == str(ws))
    assert (mine["minutes_to_agent"], mine["minutes_to_phone"], mine["minutes_to_job"]) == (6.0, 9.0, 14.0)
    assert mine["started_in_time"] is True
    other = next(w for w in onb["workspaces"] if w["workspace_id"] != str(ws))
    assert other["minutes_to_job"] is None and other["started_in_time"] is False

    assert out["jobs"]["succeeded"] == 1 and out["jobs"]["failed"] == 1 and out["jobs"]["success_pct"] == 50.0
    posts = out["posts"]
    assert (posts["verified"], posts["unknown"], posts["dry_runs"]) == (1, 1, 1)
    assert posts["success_pct"] == 50.0  # UNKNOWN counts against the rate; the dry run does not count at all


def test_pilot_report_is_for_staff_only(onboard, app):
    customer, staff = onboard(), onboard()
    assert customer.get("/v1/admin/pilot-report").status_code == 404
    with app.state.db.sessionmaker() as s:
        assert manage.grant_role(s, staff.email, "support") == 0
    out = staff.get("/v1/admin/pilot-report", params={"days": 7})
    assert out.status_code == 200 and set(out.json()) >= {"onboarding", "jobs", "posts"}
