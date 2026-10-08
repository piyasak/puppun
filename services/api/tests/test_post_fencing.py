"""G5-06: a revoked token, an expired session or an older session of the same install never gets new
posts and cannot carry on with one it held; the post goes to a valid Agent instead (or stays UNKNOWN
when Post may already have been pressed). Real Agent code over real HTTP; the phone is simulated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from api_test_shop import FULL_DAY, expire, items, set_times
from sqlalchemy import update
from test_agent_post_runner_http import FakePhone

from agent.adb import Adb
from agent.post_runner import PostRunner
from agent.server_client import ServerClient, ServerError
from clipflow_api.models import AgentSession


@pytest.fixture
def due(shop, app, server_url):
    """One due post on the shop's phone; a posting Agent on a second PC (its own installation)."""
    env = shop.env
    shop.acc.patch(f"/v1/environments/{env['id']}", json={"name": env["name"], "registered_agent_limit": 2,
                                                          "concurrent_session_limit": 2, "device_limit": 1})
    job_id, _ = shop.job(clips=1)
    series = shop.create(job_id, **FULL_DAY).json()
    set_times(app, series["id"], [-1])
    client = ServerClient(server_url)
    installation = str(uuid.uuid4())
    session = client.authenticate(shop.acc.username, shop.token, installation)
    return {"series": series, "client": client, "session": session, "installation": installation,
            "item": series["items"][0]["id"]}


def runner(tmp_path, phone):
    return PostRunner(tmp_path / "agent", lambda: Adb(phone.run), log=lambda *_: None, retry_wait_s=0.1)


def test_revoked_token_mid_transfer_stops_the_agent_and_a_new_token_finishes(shop, app, due, tmp_path, server_url):
    phone = FakePhone(shop.serial, on_push=lambda: shop.acc.post(f"/v1/agent-tokens/{shop.token_id}/revoke"))
    assert runner(tmp_path, phone).run_once(due["client"], lambda: due["session"]) == "stopped"
    assert phone.files == {}  # the half-done transfer was removed from the phone
    with pytest.raises(ServerError) as err:  # the old Agent gets nothing new
        due["client"].claim_post(due["session"], [shop.serial])
    assert (err.value.code, err.value.reason) == ("AGENT_SESSION_ENDED", "token_revoked")
    with pytest.raises(ServerError):  # nor can it sign in again with the revoked token
        due["client"].authenticate(shop.acc.username, shop.token, due["installation"])

    # The owner issues a new token; once the old lease runs out the post goes to the new session.
    fresh = shop.acc.post("/v1/agent-tokens", json={"environment_id": shop.env["id"], "name": "pc2"}).json()["token"]
    expire(app, due["item"])
    session = due["client"].authenticate(shop.acc.username, fresh, due["installation"])
    phone2 = FakePhone(shop.serial)
    assert runner(tmp_path / "2", phone2).run_once(due["client"], lambda: session) == "DRY_RUN_DONE"
    item = items(shop, due["series"]["id"])[0]
    assert item["state"] == "DRY_RUN_DONE" and item["attempts"] == 2


def test_an_older_session_of_the_same_install_is_fenced_out(shop, due, tmp_path):
    old = due["session"]
    post = due["client"].claim_post(old, [shop.serial])
    newer = due["client"].authenticate(shop.acc.username, shop.token, due["installation"])  # same PC restarted
    assert newer.generation > old.generation
    with pytest.raises(ServerError) as err:
        due["client"].post_event(old, post["id"], {"event_id": uuid.uuid4().hex, "type": "TRANSFERRING"})
    assert err.value.reason == "superseded"
    with pytest.raises(ServerError):
        due["client"].claim_post(old, [shop.serial])
    # The newer session does not inherit the old lease either: the post waits for the lease to expire.
    assert due["client"].claim_post(newer, [shop.serial]) is None


def test_an_expired_session_gets_nothing(shop, app, due):
    with app.state.db.sessionmaker() as s:
        s.execute(update(AgentSession).where(AgentSession.ended_at.is_(None),
                                             AgentSession.environment_id == uuid.UUID(shop.env["id"]))
                  .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        s.commit()
    with pytest.raises(ServerError) as err:
        due["client"].claim_post(due["session"], [shop.serial])
    assert err.value.reason == "expired"
    assert items(shop, due["series"]["id"])[0]["state"] == "SCHEDULED"


def test_revoked_after_post_was_pressed_stays_unknown(shop, app, due, live_server_url):
    live = ServerClient(live_server_url)
    session = live.authenticate(shop.acc.username, shop.token, due["installation"])
    post = live.claim_post(session, [shop.serial])
    for kind in ("TRANSFERRING", "PREPARING", "SUBMITTING"):
        live.post_event(session, post["id"], {"event_id": uuid.uuid4().hex, "type": kind})
    shop.acc.post(f"/v1/agent-tokens/{shop.token_id}/revoke")
    with pytest.raises(ServerError):  # the Agent can no longer report, not even success
        live.post_event(session, post["id"], {"event_id": uuid.uuid4().hex, "type": "VERIFYING"})
    expire(app, post["id"])
    fresh = shop.acc.post("/v1/agent-tokens", json={"environment_id": shop.env["id"], "name": "pc2"}).json()["token"]
    other = live.authenticate(shop.acc.username, fresh, due["installation"])  # the PC with a new token
    assert live.claim_post(other, [shop.serial]) is None  # nothing replayed
    item = items(shop, due["series"]["id"])[0]
    assert (item["state"], item["reason"]) == ("UNKNOWN", "AGENT_LOST_AFTER_SUBMIT")
