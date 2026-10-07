"""Simulated Agent process for API tests (installation_id + current session)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


class Agent:
    """A simulated Agent process: its own installation_id and current session."""

    def __init__(self, client: TestClient, username: str, token: str, installation_id: str | None = None):
        self.client, self.username, self.token = client, username, token
        self.installation_id = installation_id or str(uuid.uuid4())
        self.session = None
        self.generation = None

    def auth(self, **extra):
        resp = self.client.post("/v1/agent/authenticate", json={
            "username": self.username, "token": self.token, "installation_id": self.installation_id,
            "agent_version": "0.1.0"} | extra)
        if resp.status_code == 200:
            self.session, self.generation = resp.json()["session_token"], resp.json()["generation"]
        return resp

    def heartbeat(self, generation=None):
        return self.client.post("/v1/agent/heartbeat", json={"generation": generation or self.generation},
                                headers={"Authorization": f"Bearer {self.session}"})

    def post(self, path, **kw):
        return self.client.post(path, headers={"Authorization": f"Bearer {self.session}"}, **kw)
