"""Integration fixtures: a throwaway PostgreSQL database per test run, migrated with Alembic.

Needs the local compose Postgres (`docker compose up -d postgres`). If it is unreachable
the tests are skipped, and a skip is never counted as gate evidence.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from pathlib import Path

import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from api_test_tokens import SIGNING_KEY, SUPABASE_URL, mint, new_identity
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from clipflow_api.app import create_app
from clipflow_api.config import Settings

API_DIR = Path(__file__).resolve().parents[1]
ADMIN_URL = os.environ.get(
    "CLIPFLOW_TEST_DATABASE_URL", "postgresql+psycopg://clipflow:clipflow_dev@127.0.0.1:5432/clipflow"
)


def _alembic_config(url: str) -> Config:
    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture(scope="session")
def alembic_config():
    return _alembic_config


@pytest.fixture(scope="session")
def database_url():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not reachable at {make_url(ADMIN_URL).render_as_string(hide_password=True)}: {exc}")
    name = f"clipflow_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f'create database "{name}"'))
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    yield url
    with admin.connect() as conn:
        conn.execute(text(f'drop database if exists "{name}" with (force)'))
    admin.dispose()


@pytest.fixture(scope="session")
def migrated_url(database_url):
    command.upgrade(_alembic_config(database_url), "head")
    return database_url


@pytest.fixture(scope="session")
def app(migrated_url):
    # Agent sign-in rate limit is tested on its own app (test_agent_sessions); keep it out of the way here.
    settings = Settings(app_env="test", database_url=migrated_url, supabase_url=SUPABASE_URL,
                        agent_auth_rate_per_minute=10_000)
    return create_app(settings, resolve_key=lambda token: SIGNING_KEY.public_key())


@pytest.fixture
def client(app):
    return TestClient(app)


class Account:
    """An onboarded user: Supabase-style identity plus its bearer header."""

    def __init__(self, client: TestClient, user_id: uuid.UUID, email: str, body: dict):
        self.client, self.user_id, self.email, self.body = client, user_id, email, body
        self.username = body["user"]["username"]
        self.token = mint(user_id, email)

    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path, **kw):
        return self.client.get(path, headers=self.headers(), **kw)

    def post(self, path, **kw):
        return self.client.post(path, headers=self.headers(), **kw)

    def patch(self, path, **kw):
        return self.client.patch(path, headers=self.headers(), **kw)


@pytest.fixture
def onboard(client):
    def _onboard(**overrides) -> Account:
        user_id, email = new_identity()
        payload = {"username": f"u{uuid.uuid4().hex[:10]}", "accept_rights": True} | overrides
        resp = client.post("/v1/onboarding", json=payload, headers={"Authorization": f"Bearer {mint(user_id, email)}"})
        assert resp.status_code == 201, resp.text
        return Account(client, user_id, email, resp.json())

    return _onboard


# Real HTTP server on 127.0.0.1 for tests that use the Agent's own client.
@pytest.fixture(scope="session")
def server_url(app):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
