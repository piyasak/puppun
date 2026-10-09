"""E-50: the Agent setup offered on the Agents page."""

from __future__ import annotations

import pytest

SHA = "5642844f7b8604403736dfe71fcf57f79aa4628fd414c85d4d30b9ebdda16434"


@pytest.fixture
def offer(app):
    def _offer(**values):
        app.state.settings = app.state.settings.model_copy(update=values)
    original = app.state.settings
    yield _offer
    app.state.settings = original


def test_not_offered_until_configured(onboard):
    assert onboard().get("/v1/agents/download").json() == {"available": False}


def test_offered_with_version_size_and_sha(onboard, offer):
    offer(agent_setup_url="https://downloads.example.com/punpun-agent-setup-0.3.0.exe", agent_setup_version="0.3.0",
          agent_setup_sha256=SHA.upper(), agent_setup_size_mb="34.9")
    assert onboard().get("/v1/agents/download").json() == {
        "available": True, "version": "0.3.0", "url": "https://downloads.example.com/punpun-agent-setup-0.3.0.exe",
        "sha256": SHA, "size_mb": 34.9}


@pytest.mark.parametrize("values", [
    {"agent_setup_sha256": "not-a-hash"},
    {"agent_setup_version": ""},
    {"agent_setup_url": "ftp://downloads.example.com/setup.exe"},
    {"agent_setup_url": "http://downloads.example.com/setup.exe", "app_env": "staging"},
])
def test_never_offers_a_link_the_customer_cannot_check(onboard, offer, values):
    offer(**({"agent_setup_url": "https://downloads.example.com/setup.exe", "agent_setup_version": "0.3.0",
              "agent_setup_sha256": SHA} | values))
    assert onboard().get("/v1/agents/download").json() == {"available": False}


def test_needs_a_signed_in_user(client):
    assert client.get("/v1/agents/download").status_code == 401


def test_size_is_optional(onboard, offer):
    offer(agent_setup_url="https://downloads.example.com/setup.exe", agent_setup_version="0.3.0",
          agent_setup_sha256=SHA, agent_setup_size_mb="")
    assert onboard().get("/v1/agents/download").json()["size_mb"] is None
