"""Delete after post (PO 2026-10-10): a job can ask that each clip's file on the Agent's PC is deleted
for good once its post is verified, so the clips folder does not fill up.

The server only lists a clip when a post of it is VERIFIED_SUCCESS and no other post of it is still
to come or unsettled (UNKNOWN keeps the file for reconciliation), and only to the installation that
rendered it. The Agent deletes a file only while its SHA-256 still matches."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from api_test_shop import FULL_DAY
from sqlalchemy import update

from agent.post_runner import PostRunner
from agent.server_client import ServerClient
from clipflow_api.models import Clip, ScheduleItem


def mark(app, series_id, *states):
    """Settle the series' items (in seq order) as if they had been posted."""
    with app.state.db.sessionmaker() as s:
        rows = s.query(ScheduleItem).filter(ScheduleItem.series_id == uuid.UUID(series_id)).order_by(ScheduleItem.seq).all()
        for item, state in zip(rows, states, strict=False):
            item.state = state
        s.commit()


def kept_on_agent(app, clip_ids):
    """Q-33 delivery: the file stays on the Agent's PC (Shop uploads, so flip the location)."""
    with app.state.db.sessionmaker() as s:
        s.execute(update(Clip).where(Clip.id.in_([uuid.UUID(c) for c in clip_ids])).values(file_location="agent"))
        s.commit()


@pytest.fixture
def posted(shop, app):
    def make(clips=1, delete_after_post=True):
        job_id, clip_ids = shop.job(clips=clips, delete_after_post=delete_after_post)
        kept_on_agent(app, clip_ids)
        series = shop.create(job_id, **FULL_DAY).json()
        return job_id, clip_ids, series
    return make


def listed(shop):
    resp = shop.w.client.get("/v1/agent/clips/deletable", headers={"Authorization": f"Bearer {shop.w.session}"})
    assert resp.status_code == 200, resp.text
    return [i["clip_id"] for i in resp.json()["items"]]


def test_the_choice_is_made_when_creating_the_job(shop):
    job_id, _ = shop.job(clips=1, delete_after_post=True)
    assert shop.acc.get(f"/v1/jobs/{job_id}").json()["delete_after_post"] is True
    job_id, _ = shop.job(clips=1)
    assert shop.acc.get(f"/v1/jobs/{job_id}").json()["delete_after_post"] is False  # off unless asked


def test_listed_only_once_a_post_is_verified(shop, app, posted):
    _, (clip,), series = posted()
    assert listed(shop) == []  # scheduled, not posted
    mark(app, series["id"], "DRY_RUN_DONE")
    assert listed(shop) == []  # a dry run is not a post
    mark(app, series["id"], "VERIFIED_SUCCESS")
    assert listed(shop) == [clip]


@pytest.mark.parametrize("state", ["UNKNOWN", "NEEDS_ACTION", "SUBMITTING", "SCHEDULED"])
def test_unsettled_posts_keep_the_file(shop, app, posted, state):
    _, _, series = posted()
    mark(app, series["id"], state)
    assert listed(shop) == []  # UNKNOWN in particular: the file may be needed to reconcile


def test_not_listed_without_the_choice_or_to_another_pc(shop, app, client, posted):
    _, _, series = posted(delete_after_post=False)
    mark(app, series["id"], "VERIFIED_SUCCESS")
    assert listed(shop) == []
    _, (clip,), series = posted()
    mark(app, series["id"], "VERIFIED_SUCCESS")
    assert listed(shop) == [clip]
    with app.state.db.sessionmaker() as s:  # rendered by another PC of this Environment: the file is there
        other = s.query(Clip).filter(Clip.id == uuid.UUID(clip)).one().agent_installation_id
        s.execute(update(Clip).where(Clip.id == uuid.UUID(clip)).values(agent_installation_id=None))
        s.commit()
    assert other is not None  # recorded when the clip was reported
    assert listed(shop) == []
    assert shop.w.post(f"/v1/agent/clips/{clip}/file-deleted", json={"found": True}).status_code == 404


def test_agent_deletes_the_posted_file_and_reports_it(shop, app, posted, server_url, tmp_path):
    job_id, clip_ids, series = posted(clips=2)
    mark(app, series["id"], "VERIFIED_SUCCESS", "VERIFIED_SUCCESS")
    data = tmp_path / "agent-data"
    home = data / "clips" / job_id
    home.mkdir(parents=True)
    (home / "clip_01.mp4").write_bytes(shop.clip_bytes)
    (home / "clip_01.jpg").write_bytes(b"\xff\xd8\xff still")
    (home / "clip_02.mp4").write_bytes(shop.clip_bytes + b"edited")  # changed after posting: not ours to delete
    client = ServerClient(server_url)
    session = client.authenticate(shop.acc.username, shop.token, shop.w.installation_id)
    logs = []
    runner = PostRunner(data, lambda: None, log=logs.append)

    assert runner.delete_posted_clips(client, lambda: session) == [clip_ids[0]]
    assert not (home / "clip_01.mp4").exists() and not (home / "clip_01.jpg").exists()
    assert (home / "clip_02.mp4").exists()  # kept, and still listed for a person to look at
    assert any("ไม่ตรงกับที่โพสต์" in line for line in logs)
    detail = {c["id"]: c for c in shop.acc.get(f"/v1/jobs/{job_id}").json()["clips"]}
    assert detail[clip_ids[0]]["agent_file_deleted_at"] and detail[clip_ids[1]]["agent_file_deleted_at"] is None
    assert shop.w.auth().status_code == 200  # the test's own Agent signs in again (same installation)
    assert listed(shop) == [clip_ids[1]]
    again = shop.w.post(f"/v1/agent/clips/{clip_ids[0]}/file-deleted", json={"found": True})
    assert again.status_code == 200  # a repeated report is harmless

    # Gone means gone: it cannot be scheduled again
    resp = shop.preview(job_id, **FULL_DAY).json()
    excluded = {e["clip_id"]: e["reason"] for e in (resp.get("excluded") or resp["details"]["excluded"])}
    assert excluded[clip_ids[0]] == "FILE_DELETED"


def test_a_file_already_gone_is_reported_as_not_found(shop, app, posted, server_url, tmp_path):
    _, (clip,), series = posted()
    mark(app, series["id"], "VERIFIED_SUCCESS")
    client = ServerClient(server_url)
    session = client.authenticate(shop.acc.username, shop.token, shop.w.installation_id)
    assert PostRunner(Path(tmp_path), lambda: None, log=lambda m: None).delete_posted_clips(client, lambda: session) == [clip]
    assert shop.w.auth().status_code == 200
    assert listed(shop) == []
