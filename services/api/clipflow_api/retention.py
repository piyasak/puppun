"""Retention of clip files (P6.6, NF-06, E-46).

A delivered clip file is deleted once it is older than its plan's `retention_days` (default 30,
D05), counted from upload. It is kept, whatever its age, while it may still be needed:
- its job is still running (never delete the inputs of active work);
- a schedule item for it has not finished (scheduled, being posted, needs action or unknown).

The clip row, its metadata, hashes, approvals and the posting history stay: only the stored file
goes, and the preview answers CLIP_FILE_EXPIRED afterwards. Files on the customer's PC are the
Agent's business (it keeps its own copies for posting, Q-15).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .entitlements import entitlement
from .jobs import TERMINAL
from .models import Clip, Job, ScheduleItem

FINISHED_ITEMS = ("VERIFIED_SUCCESS", "DRY_RUN_DONE", "CANCELLED", "SKIPPED")


@dataclass
class Sweep:
    deleted: list[str] = field(default_factory=list)
    kept_in_use: list[str] = field(default_factory=list)


def sweep(db: Session, storage, at: datetime, *, dry_run: bool = False, limit: int = 500) -> Sweep:
    result = Sweep()
    if not dry_run:
        from . import diagnostics

        diagnostics.purge(db, storage, at)  # screen captures: KEEP_DAYS, whatever the plan
    candidates = db.execute(
        select(Clip, Job).join(Job, Job.id == Clip.job_id)
        .where(Clip.storage_key.is_not(None), Clip.uploaded_at.is_not(None))
        .order_by(Clip.uploaded_at).limit(limit).with_for_update(of=Clip, skip_locked=True)).all()
    retention: dict = {}
    for clip, job in candidates:
        if clip.workspace_id not in retention:
            retention[clip.workspace_id] = timedelta(days=entitlement(db, clip.workspace_id).plan.retention_days)
        if clip.uploaded_at > at - retention[clip.workspace_id]:
            continue
        busy = job.state not in TERMINAL or db.scalar(select(exists().where(
            ScheduleItem.clip_id == clip.id, ScheduleItem.state.not_in(FINISHED_ITEMS))))
        if busy:
            result.kept_in_use.append(str(clip.id))
            continue
        if not dry_run:
            storage.delete(clip.storage_key)
            clip.storage_key, clip.file_deleted_at = None, at
        result.deleted.append(str(clip.id))
    return result
