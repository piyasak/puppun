"""Posts at once per Environment (Q-54, PO 2026-10-23): as many as its phones, or a lower number the owner sets."""

from __future__ import annotations

from api_test_shop import FULL_DAY, Shop, claim, ev, set_times


def busy_shop(onboard, client, real_clip, phones=3):
    shop = Shop(onboard(), client, real_clip, devices=phones)
    serials = [d["serial"] for d in shop.acc.get("/v1/devices").json()["items"]]
    for device in shop.devices:
        job_id, _ = shop.job(clips=1)
        series = shop.create(job_id, device=device, **FULL_DAY).json()
        set_times(client.app, series["id"], [-1])
    return shop, serials


def test_by_default_every_phone_may_post_at_once(onboard, client, real_clip):
    shop, serials = busy_shop(onboard, client, real_clip)
    env = shop.acc.get("/v1/environments").json()["items"][0]
    assert env["max_parallel_posts"] is None and env["parallel_posts_cap"] == 3
    claimed = [claim(shop.w, serials) for _ in range(3)]
    assert all(claimed) and len({p["device"]["serial"] for p in claimed}) == 3


def test_a_lower_cap_holds_back_the_next_post_until_one_finishes(onboard, client, real_clip):
    shop, serials = busy_shop(onboard, client, real_clip)
    env_id = shop.env["id"]
    set_cap = shop.acc.patch(f"/v1/environments/{env_id}", json={"max_parallel_posts": 1})
    assert set_cap.status_code == 200 and set_cap.json()["parallel_posts_cap"] == 1

    first = claim(shop.w, serials)
    assert first is not None and claim(shop.w, serials) is None  # the cap: nothing else while one runs
    for state in ("TRANSFERRING", "PREPARING"):
        ev(shop.w, first["id"], state)
    assert claim(shop.w, serials) is None
    ev(shop.w, first["id"], "DRY_RUN_DONE")
    second = claim(shop.w, serials)
    assert second is not None and second["device"]["serial"] != first["device"]["serial"]

    assert shop.acc.patch(f"/v1/environments/{env_id}", json={"max_parallel_posts": 4}).json()["code"] == "VALIDATION_ERROR"
    back = shop.acc.patch(f"/v1/environments/{env_id}", json={"max_parallel_posts": 0}).json()
    assert back["max_parallel_posts"] is None and back["parallel_posts_cap"] == 3  # 0 = as many as the phones
    assert claim(shop.w, serials) is not None  # room again


def test_another_workspace_cannot_change_the_cap(onboard, client, real_clip):
    shop, _ = busy_shop(onboard, client, real_clip, phones=1)
    other = onboard()
    assert other.patch(f"/v1/environments/{shop.env['id']}", json={"max_parallel_posts": 1}).status_code == 404
