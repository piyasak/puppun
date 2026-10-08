"""P4.4: pause/resume with a server preview and no catch-up burst (G4-02); editing unstarted
posts with version and claim checks (G4-04)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from api_test_shop import claim, ev, items, schedule, set_times

BKK = ZoneInfo("Asia/Bangkok")


def local(at: datetime) -> str:
    return at.astimezone(BKK).strftime("%Y-%m-%dT%H:%M")


def times(shop, series_id):
    return [datetime.fromisoformat(i["scheduled_at"]) for i in items(shop, series_id)]


def test_paused_series_hands_out_nothing_and_resumes_without_a_burst(shop, app):
    series = schedule(shop, clips=3, interval_hours=2)
    paused = shop.acc.post(f"/v1/schedules/{series['id']}/pause").json()
    assert paused["state"] == "PAUSED"
    set_times(app, series["id"], [-240, -120, -30])  # all three fell due while paused
    assert claim(shop.w, [shop.serial]) is None

    preview = shop.acc.post(f"/v1/schedules/{series['id']}/resume/preview").json()
    assert [m["seq"] for m in preview["moves"]] == [1, 2, 3]
    planned = [datetime.fromisoformat(m["to"]) for m in preview["moves"]]
    assert planned[1] - planned[0] == timedelta(hours=2) and planned[2] - planned[1] == timedelta(hours=2)
    assert times(shop, series["id"])[0] < datetime.now(UTC)  # preview changed nothing

    stale = shop.acc.post(f"/v1/schedules/{series['id']}/resume", json={"expected_version": 1})
    assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"
    resumed = shop.acc.post(f"/v1/schedules/{series['id']}/resume",
                            json={"expected_version": preview["series_version"]}).json()
    assert resumed["state"] == "ACTIVE"
    after = times(shop, series["id"])
    assert after[1] - after[0] == timedelta(hours=2) and after[2] - after[1] == timedelta(hours=2)
    assert {i["reason"] for i in resumed["items"]} == {"RESUMED"}
    assert claim(shop.w, [shop.serial])["id"] == series["items"][0]["id"]  # one now, the rest later
    assert claim(shop.w, [shop.serial]) is None


def test_resume_keeps_future_times_unchanged(shop):
    series = schedule(shop, clips=2)
    before = times(shop, series["id"])
    shop.acc.post(f"/v1/schedules/{series['id']}/pause")
    assert shop.acc.post(f"/v1/schedules/{series['id']}/resume/preview").json()["moves"] == []
    shop.acc.post(f"/v1/schedules/{series['id']}/resume", json={"expected_version": 2})
    assert times(shop, series["id"]) == before


def test_pause_does_not_stop_a_post_already_on_the_phone(shop, app):
    series = schedule(shop, clips=2)
    set_times(app, series["id"], [-2, -1])
    post = claim(shop.w, [shop.serial])
    shop.acc.post(f"/v1/schedules/{series['id']}/pause")
    for kind in ("TRANSFERRING", "PREPARING", "DRY_RUN_DONE"):
        assert ev(shop.w, post["id"], kind).status_code == 200  # followed to its result (FR-19)
    assert claim(shop.w, [shop.serial]) is None  # but nothing new starts
    assert shop.acc.post(f"/v1/schedules/{series['id']}/pause").json()["code"] == "SERIES_NOT_ACTIVE"


def test_edit_an_unstarted_post(shop):  # G4-04
    series = schedule(shop, clips=3, interval_hours=2)
    first, second, third = items(shop, series["id"])
    t1, t3 = datetime.fromisoformat(first["scheduled_at"]), datetime.fromisoformat(third["scheduled_at"])

    def patch(item, at, version=None):
        return shop.acc.patch(f"/v1/schedule-items/{item['id']}", json={
            "expected_state_version": version or item["state_version"], "scheduled_local": local(at)})

    moved = patch(second, t1 + timedelta(minutes=30))
    assert moved.status_code == 200 and moved.json()["scheduled_at"] == (t1 + timedelta(minutes=30)).isoformat()
    assert moved.json()["reason"] == "EDITED"
    assert patch(second, t1 + timedelta(minutes=45)).json()["code"] == "VERSION_CONFLICT"  # stale version
    current = items(shop, series["id"])[1]
    assert patch(current, t3 + timedelta(minutes=5)).json()["code"] == "ITEM_ORDER"  # would jump clip 3
    assert patch(current, t1 - timedelta(minutes=5)).json()["code"] == "ITEM_ORDER"
    assert patch(current, datetime(2020, 1, 1, tzinfo=UTC)).json()["code"] == "START_IN_PAST"


def test_edit_respects_the_window_and_the_claim_boundary(shop, app):
    job_id, _ = shop.job(clips=1)
    series = shop.create(job_id, window_start="09:00", window_end="21:00").json()
    item = series["items"][0]
    day = datetime.fromisoformat(item["scheduled_at"]).astimezone(BKK).date()
    late = datetime(day.year, day.month, day.day, 22, 0, tzinfo=BKK)
    resp = shop.acc.patch(f"/v1/schedule-items/{item['id']}", json={
        "expected_state_version": item["state_version"], "scheduled_local": local(late)})
    assert resp.status_code == 422 and resp.json()["code"] == "OUTSIDE_WINDOW"

    set_times(app, series["id"], [-1])
    claim(shop.w, [shop.serial])
    claimed = items(shop, series["id"])[0]
    resp = shop.acc.patch(f"/v1/schedule-items/{item['id']}", json={
        "expected_state_version": claimed["state_version"], "scheduled_local": local(late - timedelta(hours=2))})
    assert resp.status_code == 409 and resp.json()["code"] == "ITEM_NOT_EDITABLE"


def calendar(acc, start, end):
    return acc.get("/v1/schedule-items", params={"start": start.isoformat(), "end": end.isoformat()})


def test_calendar_shows_planned_and_actual_times_and_the_phone_queue(shop, app, onboard):  # G4-05 UI data
    first = schedule(shop, clips=1)
    second = schedule(shop, clips=1)  # same phone, same slot: queued behind the first (Q-05)
    t = datetime.fromisoformat(first["items"][0]["scheduled_at"])
    rows = calendar(shop.acc, t - timedelta(hours=1), t + timedelta(hours=1)).json()["items"]
    assert [r["series_id"] for r in rows] == [first["id"], second["id"]]
    assert [r["queued_behind"] for r in rows] == [False, True]
    assert rows[0]["device_name"] == "POCO" and rows[0]["account"] == "handle0" and rows[0]["job"]["source"]

    set_times(app, first["id"], [-1])
    claim(shop.w, [shop.serial])
    now = datetime.now(UTC)
    row = calendar(shop.acc, now - timedelta(hours=1), now + timedelta(hours=1)).json()["items"][0]
    assert row["state"] == "CLAIMED" and row["claimed_at"] and 0 <= row["delay_s"] <= 120
    assert row["scheduled_at"] != row["claimed_at"]  # plan and reality side by side

    stranger = onboard()
    assert calendar(stranger, now - timedelta(days=7), now + timedelta(days=7)).json()["items"] == []
    bad = calendar(shop.acc, now, now - timedelta(hours=1))
    assert bad.status_code == 422 and bad.json()["code"] == "RANGE_INVALID"
