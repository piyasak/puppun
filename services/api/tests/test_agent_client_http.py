"""The real Agent client (`agent/`) against a real uvicorn server over HTTP (FR-14, T03/T04).

Still a local test: the server runs on 127.0.0.1 with the test database and simulated
Supabase identities. It proves client + server work together; it is not a field test.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from agent.identity import load_or_create_installation_id
from agent.server_client import ServerClient, ServerError, run_connection


@pytest.fixture
def owner(onboard):
    acc = onboard()
    env = acc.post("/v1/environments", json={"name": "office", "registered_agent_limit": 1,
                                             "concurrent_session_limit": 1}).json()
    acc.agent_token = acc.post("/v1/agent-tokens", json={"environment_id": env["id"], "name": "pc"}).json()["token"]
    return acc


def test_restart_and_reconnect_twenty_times_over_http(server_url, owner, tmp_path):  # T03
    client = ServerClient(server_url)
    for _ in range(20):
        installation_id = load_or_create_installation_id(tmp_path)  # what a restart does
        session = client.authenticate(owner.username, owner.agent_token, installation_id)
        client.heartbeat(session)
    assert session.generation == 20
    agents = owner.get("/v1/agents").json()["items"]
    assert len(agents) == 1 and agents[0]["presence"] == "online"
    # Registration limit is 1 and was never exceeded by the reconnects.
    assert owner.get("/v1/workspace/usage").json()["in_use"]["registered_agent_limit"] == 1


def test_copied_install_running_twice_is_fenced_over_http(server_url, owner, tmp_path):  # T04
    installation_id = load_or_create_installation_id(tmp_path)
    a = ServerClient(server_url)
    first = a.authenticate(owner.username, owner.agent_token, installation_id)
    second = a.authenticate(owner.username, owner.agent_token, installation_id)
    with pytest.raises(ServerError) as exc:
        a.heartbeat(first)
    assert exc.value.reason == "superseded"
    assert a.heartbeat(second)["generation"] == second.generation


def test_run_loop_stops_when_the_token_is_revoked(server_url, owner, tmp_path):
    client = ServerClient(server_url)
    token_id = owner.get("/v1/agent-tokens").json()["items"][0]["id"]
    calls = []

    def sleep(_):
        calls.append(1)
        if len(calls) == 2:
            owner.post(f"/v1/agent-tokens/{token_id}/revoke")

    result = run_connection(client, owner.username, owner.agent_token, load_or_create_installation_id(tmp_path),
                            duration_s=None, sleep=sleep, log=lambda *_: None)
    assert result.stopped_because == "token_revoked" and result.heartbeats == 1


def test_cli_connect_keeps_the_token_out_of_argv_and_output(server_url, owner, tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "agent.cli", "connect", "--server", server_url, "--username", owner.username,
         "--seconds", "0", "--data-dir", str(tmp_path)],
        env={**__import__("os").environ, "CLIPFLOW_AGENT_TOKEN": owner.agent_token},
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "connected: environment=office" in proc.stdout
    assert owner.agent_token not in proc.stdout + proc.stderr
    assert (tmp_path / "installation_id").exists()
