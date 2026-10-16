"""NF-01 / G2-01: one Workspace can never read or change another Workspace's resources."""

from __future__ import annotations

import uuid

from clipflow_api.models import AuditEvent, Base


def _strip(resp):
    return {k: v for k, v in resp.json().items() if k != "request_id"}


def test_list_shows_only_own_environments(onboard):
    a, b = onboard(), onboard()
    a.post("/v1/environments", json={"name": "สำนักงาน"})
    b.post("/v1/environments", json={"name": "บ้าน"})
    assert [e["name"] for e in a.get("/v1/environments").json()["items"]] == ["สำนักงาน"]
    assert [e["name"] for e in b.get("/v1/environments").json()["items"]] == ["บ้าน"]


def test_other_workspace_resource_looks_exactly_like_a_missing_one(onboard):
    a, b = onboard(), onboard()
    env_id = a.post("/v1/environments", json={"name": "A1"}).json()["id"]

    foreign = b.get(f"/v1/environments/{env_id}")
    missing = b.get(f"/v1/environments/{uuid.uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert _strip(foreign) == _strip(missing)


def test_cannot_modify_another_workspace_resource(onboard):
    a, b = onboard(), onboard()
    env_id = a.post("/v1/environments", json={"name": "A1"}).json()["id"]
    assert b.patch(f"/v1/environments/{env_id}", json={"name": "taken over"}).status_code == 404
    assert a.get(f"/v1/environments/{env_id}").json()["name"] == "A1"


def test_same_name_is_allowed_in_different_workspaces(onboard):
    a, b = onboard(), onboard()
    assert a.post("/v1/environments", json={"name": "หลัก"}).status_code == 201
    assert b.post("/v1/environments", json={"name": "หลัก"}).status_code == 201
    dup = a.post("/v1/environments", json={"name": "หลัก"})
    assert dup.status_code == 409 and dup.json()["code"] == "NAME_TAKEN"


def test_not_onboarded_user_cannot_reach_tenant_resources(client):
    from api_test_tokens import mint, new_identity

    user_id, email = new_identity()
    resp = client.get("/v1/environments", headers={"Authorization": f"Bearer {mint(user_id, email)}"})
    assert resp.status_code == 403 and resp.json()["code"] == "ONBOARDING_REQUIRED"


def test_every_customer_table_carries_a_non_null_workspace_id():
    """PRD §F: tenant-owned rows have workspace_id. Global tables are listed explicitly."""
    # payment_events is the provider's log: an event can arrive before (or without) a known payment,
    # so it is global and reaches a Workspace only through payments (E-45).
    # ui_profiles (Q-50): one TikTok UI profile for every Agent, edited by platform admins only
    global_tables = {"workspaces", "users", "plans", "payment_events", "ui_profiles"}
    nullable_by_design = {AuditEvent.__tablename__}  # system events may have no workspace
    for table in Base.metadata.sorted_tables:
        if table.name in global_tables:
            continue
        assert "workspace_id" in table.c, f"{table.name} has no workspace_id"
        if table.name not in nullable_by_design:
            assert not table.c.workspace_id.nullable, f"{table.name}.workspace_id is nullable"
