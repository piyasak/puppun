"""Pilot report (P7.2-P7.4, G7-01/G7-02): onboarding times and job/post outcomes from the server's
own records, for a window of time. Nothing is dropped to improve a rate: every finished job and post
in the window is counted, and in-progress ones are listed apart (PRD P7.4).

- Onboarding: per Workspace created in the window, minutes from sign-up to the first Agent install,
  first phone and first job. "Started" = first job within 20 minutes of sign-up (G7-01: >= 80 % of
  >= 10 new users).
- Jobs: success = clips delivered (READY_FOR_REVIEW); failed = FAILED / NEEDS_ACTION;
  CANCELLED is the customer's choice and is shown but not in the rate.
- Posts: live = VERIFIED_SUCCESS vs UNKNOWN / NEEDS_ACTION / failed; dry runs (DRY_RUN_DONE) are a
  separate line and never count as posts (G7-02 needs >= 50 authorized posts at >= 95 %).
"""

from __future__ import annotations

from datetime import datetime
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AgentInstallation, Device, Job, ScheduleItem, Workspace

START_MINUTES = 20
JOB_OK = ("READY_FOR_REVIEW",)  # clips delivered; approval is per clip
JOB_FAILED = ("FAILED", "NEEDS_ACTION")
POST_FAILED = ("NEEDS_ACTION",)  # a retryable failure goes back to SCHEDULED until retries are spent
POST_OPEN = ("SCHEDULED", "CLAIMED", "TRANSFERRING", "PREPARING", "SUBMITTING", "VERIFYING")


def _minutes(start: datetime, end: datetime | None) -> float | None:
    return None if end is None else round((end - start).total_seconds() / 60, 1)


def _rate(ok: int, bad: int) -> float | None:
    return None if ok + bad == 0 else round(100 * ok / (ok + bad), 1)


def report(db: Session, since: datetime, until: datetime) -> dict:
    firsts = {}
    for model, key in ((AgentInstallation, "agent"), (Device, "phone"), (Job, "job")):
        rows = db.execute(select(model.workspace_id, func.min(model.created_at)).group_by(model.workspace_id)).all()
        firsts[key] = dict(rows)
    users = []
    for ws in db.scalars(select(Workspace).where(Workspace.created_at >= since, Workspace.created_at < until)
                         .order_by(Workspace.created_at)):
        row = {"workspace_id": str(ws.id), "name": ws.name, "signed_up_at": ws.created_at.isoformat()}
        for key in ("agent", "phone", "job"):
            row[f"minutes_to_{key}"] = _minutes(ws.created_at, firsts[key].get(ws.id))
        row["started_in_time"] = row["minutes_to_job"] is not None and row["minutes_to_job"] <= START_MINUTES
        users.append(row)
    started = sum(u["started_in_time"] for u in users)
    to_job = [u["minutes_to_job"] for u in users if u["minutes_to_job"] is not None]

    jobs = dict(db.execute(select(Job.state, func.count()).where(Job.created_at >= since, Job.created_at < until)
                           .group_by(Job.state)).all())
    j_ok = sum(jobs.get(s, 0) for s in JOB_OK)
    j_bad = sum(jobs.get(s, 0) for s in JOB_FAILED)

    posts = dict(db.execute(select(ScheduleItem.state, func.count())
                            .where(ScheduleItem.scheduled_at >= since, ScheduleItem.scheduled_at < until)
                            .group_by(ScheduleItem.state)).all())
    p_ok = posts.get("VERIFIED_SUCCESS", 0)
    p_unknown = posts.get("UNKNOWN", 0)
    p_bad = sum(posts.get(s, 0) for s in POST_FAILED)

    return {
        "since": since.isoformat(), "until": until.isoformat(),
        "onboarding": {
            "new_workspaces": len(users), "started_within_minutes": START_MINUTES, "started": started,
            "started_pct": _rate(started, len(users) - started),
            "median_minutes_to_first_job": median(to_job) if to_job else None,
            "target": "≥ 10 ผู้ใช้ใหม่ และ ≥ 80 % เริ่มใช้งานได้ใน 20 นาที (G7-01)",
            "workspaces": users,
        },
        "jobs": {
            "by_state": jobs, "succeeded": j_ok, "failed": j_bad, "cancelled": jobs.get("CANCELLED", 0),
            "in_progress": sum(n for s, n in jobs.items() if s not in JOB_OK + JOB_FAILED + ("CANCELLED",)),
            "success_pct": _rate(j_ok, j_bad),
            "target": "≥ 50 งาน สำเร็จ ≥ 95 % (G7-02)",
        },
        "posts": {
            "by_state": posts, "verified": p_ok, "unknown": p_unknown, "failed": p_bad,
            "dry_runs": posts.get("DRY_RUN_DONE", 0),
            "in_progress": sum(posts.get(s, 0) for s in POST_OPEN),
            "success_pct": _rate(p_ok, p_bad + p_unknown),
            "target": "≥ 50 โพสต์จริงที่ได้รับอนุญาต สำเร็จ ≥ 95 % และรายงาน Unknown แยก (G7-02); dry run ไม่นับ",
        },
    }
