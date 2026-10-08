"""P5.5 (G5-04): an UNKNOWN post is settled only by a person with evidence; nothing is retried
without a confirmed "not published"; the phone stays paused while a post is unknown. Posts parked
for operational reasons can be retried once fixed."""

from __future__ import annotations

from api_test_shop import Worker, claim, ev, expire, items, schedule, set_times


def unknown_post(shop, app, live_client, clips=2):
    """A series whose first post was submitted and then lost (Agent gone after Submit)."""
    series = schedule(shop, clips=clips)
    lw = Worker(live_client, shop.acc.username, shop.token, shop.w.installation_id)
    assert lw.auth().status_code == 200
    set_times(app, series["id"], [-2] + [-1] * (clips - 1))
    post = claim(lw, [shop.serial])
    for kind in ("TRANSFERRING", "PREPARING", "SUBMITTING"):
        assert ev(lw, post["id"], kind).status_code == 200
    expire(app, post["id"])
    assert claim(lw, [shop.serial]) is None  # phone paused: the unknown post may still be uploading
    item = items(shop, series["id"])[0]
    assert item["state"] == "UNKNOWN"
    return series, item, lw


def resolve(shop, item, decision, evidence="ตรวจในแอป TikTok ของ @handle0 แล้ว", version=None):
    return shop.acc.post(f"/v1/schedule-items/{item['id']}/resolve", json={
        "decision": decision, "evidence": evidence, "expected_state_version": version or item["state_version"]})


def test_found_published_needs_evidence_and_frees_the_phone(shop, app, live_client):
    series, item, lw = unknown_post(shop, app, live_client)
    assert resolve(shop, item, "found_published", evidence="").json()["code"] == "EVIDENCE_REQUIRED"
    assert resolve(shop, item, "maybe").status_code == 422
    done = resolve(shop, item, "found_published", evidence="https://www.tiktok.com/@handle0/video/123")
    assert done.status_code == 200
    body = done.json()
    assert body["state"] == "VERIFIED_SUCCESS" and body["verified_at"]
    assert body["evidence"]["decision"] == "found_published" and "tiktok.com" in body["evidence"]["value"]
    assert claim(lw, [shop.serial])["id"] == series["items"][1]["id"]  # the phone takes the next post


def test_confirmed_not_published_is_retried_once_at_the_next_allowed_time(shop, app, live_client):
    series, item, lw = unknown_post(shop, app, live_client, clips=1)
    back = resolve(shop, item, "confirmed_not_published", evidence="ไม่มีโพสต์ในโปรไฟล์และร่าง")
    assert back.json()["state"] == "SCHEDULED" and back.json()["reason"] == "RESOLVED_NOT_PUBLISHED"
    again = claim(lw, [shop.serial])
    assert again["id"] == item["id"]
    assert claim(lw, [shop.serial]) is None  # exactly one post on the phone


def test_still_unknown_keeps_the_phone_paused(shop, app, live_client):
    series, item, lw = unknown_post(shop, app, live_client)
    kept = resolve(shop, item, "still_unknown", evidence="แอปยังค้างหน้าอัปโหลด ตรวจอีกครั้งพรุ่งนี้")
    assert kept.json()["state"] == "UNKNOWN" and kept.json()["evidence"]["decision"] == "still_unknown"
    assert claim(lw, [shop.serial]) is None
    stale = resolve(shop, item, "found_published", version=item["state_version"])  # an old screen
    assert stale.json()["code"] == "VERSION_CONFLICT"


def test_only_unknown_posts_are_resolved_and_only_by_their_owner(shop, app, onboard):
    series = schedule(shop, clips=1)
    item = series["items"][0]
    assert resolve(shop, item, "found_published").json()["code"] == "NOT_UNKNOWN"
    assert onboard().post(f"/v1/schedule-items/{item['id']}/resolve", json={
        "decision": "found_published", "evidence": "xxxxx", "expected_state_version": 1}).status_code == 404


def test_retry_after_an_operational_problem(shop, app):
    series = schedule(shop, clips=1)
    set_times(app, series["id"], [-1])
    post = claim(shop.w, [shop.serial])
    ev(shop.w, post["id"], "NEEDS_ACTION", code="ACCOUNT_MISMATCH")
    item = items(shop, series["id"])[0]
    resp = shop.acc.post(f"/v1/schedule-items/{item['id']}/retry", json={"expected_state_version": item["state_version"]})
    assert resp.status_code == 200 and resp.json()["state"] == "SCHEDULED" and resp.json()["attempts"] == 0
    assert claim(shop.w, [shop.serial])["id"] == item["id"]


def test_retry_is_refused_when_the_text_changed(shop, app):
    series = schedule(shop, clips=1)
    clip_id = series["items"][0]["clip_id"]
    shop.acc.patch(f"/v1/clips/{clip_id}/metadata", json={"expected_version": 1, "caption": "ใหม่"})
    item = items(shop, series["id"])[0]
    assert item["reason"] == "APPROVAL_CHANGED"
    resp = shop.acc.post(f"/v1/schedule-items/{item['id']}/retry", json={"expected_state_version": item["state_version"]})
    assert resp.status_code == 409 and resp.json()["code"] == "NOT_RETRYABLE"  # approve the new text instead


def test_everything_waiting_for_a_person_is_listed_in_one_place(shop, app, live_client, onboard):  # P5.7
    series, item, lw = unknown_post(shop, app, live_client)
    rows = shop.acc.get("/v1/schedule-items", params={"attention": "true"}).json()["items"]
    assert [(r["id"], r["state"], r["reason"]) for r in rows] == [(item["id"], "UNKNOWN", "AGENT_LOST_AFTER_SUBMIT")]
    assert rows[0]["job"]["id"] and rows[0]["account"] == "handle0"
    assert onboard().get("/v1/schedule-items", params={"attention": "true"}).json()["items"] == []
    resolve(shop, item, "found_published", evidence="https://www.tiktok.com/@handle0/video/1")
    assert shop.acc.get("/v1/schedule-items", params={"attention": "true"}).json()["items"] == []
    assert shop.acc.get("/v1/schedule-items").status_code == 422  # the calendar still needs a range
