"""FR-13 / G2-03 (limits part): Environment limits are allocations of plan-wide caps.

Demo plan `trial` v1 (migration 0002): 2 registered agents, 2 concurrent sessions, 3 devices.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient


def env(acc, name, agents=1, sessions=1, devices=1):
    return acc.post("/v1/environments", json={"name": name, "registered_agent_limit": agents,
                                               "concurrent_session_limit": sessions, "device_limit": devices})


def test_new_workspace_is_on_the_demo_plan(onboard):
    usage = onboard().get("/v1/workspace/usage").json()
    assert usage["plan"]["code"] == "trial" and usage["plan"]["is_demo"] and usage["plan"]["status"] == "trial"  # a new Workspace starts on a trial cycle (E-45)
    assert usage["caps"] == {"registered_agent_limit": 2, "concurrent_session_limit": 2, "device_limit": 3}
    assert usage["allocated"] == {"registered_agent_limit": 0, "concurrent_session_limit": 0, "device_limit": 0}


def test_more_environments_do_not_multiply_the_plan(onboard):
    acc = onboard()
    assert env(acc, "office").status_code == 201
    assert env(acc, "home").status_code == 201
    third = env(acc, "shop")
    assert third.status_code == 409 and third.json()["code"] == "PLAN_LIMIT_EXCEEDED"
    over = {d["limit"]: d for d in third.json()["details"]["limits"]}
    assert over["registered_agent_limit"] == {"limit": "registered_agent_limit", "plan_cap": 2,
                                              "allocated_elsewhere": 2, "requested": 1}
    # A zero-agent Environment still fits (e.g. devices only), as long as devices fit.
    assert env(acc, "spare", agents=0, sessions=0, devices=1).status_code == 201
    assert env(acc, "spare2", agents=0, sessions=0, devices=1).status_code == 409
    assert acc.get("/v1/workspace/usage").json()["allocated"] == {
        "registered_agent_limit": 2, "concurrent_session_limit": 2, "device_limit": 3}


def test_one_environment_cannot_exceed_the_plan(onboard):
    resp = env(onboard(), "big", agents=3, sessions=1, devices=1)
    assert resp.status_code == 409 and resp.json()["code"] == "PLAN_LIMIT_EXCEEDED"


def test_sessions_cannot_exceed_registered_agents(onboard):
    acc = onboard()
    assert env(acc, "bad", agents=1, sessions=2).status_code == 422
    env_id = env(acc, "ok", agents=1, sessions=1).json()["id"]
    resp = acc.patch(f"/v1/environments/{env_id}", json={"concurrent_session_limit": 2})
    assert resp.status_code == 422


def test_update_counts_other_environments_not_itself(onboard):
    acc = onboard()
    a = env(acc, "a").json()["id"]
    env(acc, "b")
    # a: 1 -> 1 (unchanged) must not be blocked by its own allocation
    assert acc.patch(f"/v1/environments/{a}", json={"name": "a2", "device_limit": 2}).status_code == 200
    resp = acc.patch(f"/v1/environments/{a}", json={"registered_agent_limit": 2})
    assert resp.status_code == 409  # b already holds 1 of the 2 agents
    assert acc.get(f"/v1/environments/{a}").json()["registered_agent_limit"] == 1


def test_negative_limits_are_rejected(onboard):
    assert env(onboard(), "neg", agents=-1, sessions=0).status_code == 422


def test_concurrent_creates_cannot_overshoot_the_cap(onboard, app):
    """Six simultaneous requests for 1 agent each; the plan allows 2 in total."""
    acc = onboard()

    def create(i):
        with TestClient(app) as c:
            return c.post("/v1/environments", headers=acc.headers(),
                          json={"name": f"race-{i}", "registered_agent_limit": 1,
                                "concurrent_session_limit": 1, "device_limit": 0}).status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        codes = sorted(pool.map(create, range(6)))
    assert codes == [201, 201, 409, 409, 409, 409]
    assert acc.get("/v1/workspace/usage").json()["allocated"]["registered_agent_limit"] == 2
