"""G2-05 / E-49: what the staging image relies on.

- DB_SCHEMA puts every table and alembic_version in their own schema, never `public` (on Supabase,
  `public` is published by its REST API to anyone with the public key), and the app reads from it.
- WEB_DIST serves the built web app on the API's origin without hiding API 404s.
"""

from __future__ import annotations

from alembic import command
from api_test_tokens import SIGNING_KEY, SUPABASE_URL
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from clipflow_api.app import create_app
from clipflow_api.config import Settings
from clipflow_api.db import Database, driver_url

SCHEMA = "staging_check"


def test_db_schema_keeps_every_table_out_of_public(database_url, alembic_config, monkeypatch):
    monkeypatch.setenv("DB_SCHEMA", SCHEMA)
    command.upgrade(alembic_config(database_url), "head")
    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names(schema=SCHEMA))
        assert {"alembic_version", "workspaces", "users", "jobs", "schedule_items", "plans"} <= tables
        # The app's own connections see the schema: the seeded plans are there.
        db = Database(database_url, SCHEMA)
        with db.sessionmaker() as s:
            assert s.execute(text("select count(*) from plans")).scalar() > 0
            assert s.execute(text("show search_path")).scalar().strip('"') == SCHEMA
        db.engine.dispose()
        # Downgrade works inside the schema too (rollback rehearsal), then back to head.
        command.downgrade(alembic_config(database_url), "base")
        assert set(inspect(engine).get_table_names(schema=SCHEMA)) <= {"alembic_version"}
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'drop schema if exists "{SCHEMA}" cascade'))
        engine.dispose()


def test_build_id_comes_from_the_image_or_the_deployed_commit(migrated_url, storage, monkeypatch):
    settings = Settings(app_env="staging", database_url=migrated_url, supabase_url=SUPABASE_URL)

    def build():
        app = create_app(settings, resolve_key=lambda token: SIGNING_KEY.public_key(), storage=storage)
        return TestClient(app).get("/healthz").json()["build"]

    monkeypatch.delenv("BUILD_ID", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "07cdbbd1234567890")
    assert build() == "07cdbbd"  # Render: the commit it deployed
    monkeypatch.setenv("BUILD_ID", "v2")
    assert build() == "v2"  # an explicit image build id wins


def test_dashboard_style_database_urls_are_accepted():
    assert driver_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert driver_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert driver_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db"


def test_db_schema_rejects_anything_but_a_plain_name():
    import pytest

    for bad in ("Public", 'x"; drop table users; --', "a-b", "1abc"):
        with pytest.raises(RuntimeError):
            Database("postgresql+psycopg://u@127.0.0.1/x", bad)


def test_web_app_is_served_on_the_api_origin(migrated_url, storage, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>punpun</title>", encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    settings = Settings(app_env="staging", database_url=migrated_url, supabase_url=SUPABASE_URL, web_dist=str(dist))
    client = TestClient(create_app(settings, resolve_key=lambda token: SIGNING_KEY.public_key(), storage=storage))

    page = client.get("/jobs/123")  # a client-side route, reloaded
    assert page.status_code == 200 and "<title>punpun</title>" in page.text
    assert page.headers["cache-control"] == "no-cache"
    assert client.get("/").text == page.text
    assert client.get("/assets/index-abc.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    missing = client.get("/v1/no-such-thing")
    assert missing.status_code == 404 and missing.json()["code"] == "NOT_FOUND"
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.head("/jobs/123").status_code == 200  # HEAD (link checkers, uptime monitors) gets the page too
    assert client.get("/v1/billing/plans").status_code == 200
    # A missing API endpoint is 404 for every method (an Agent got 405 for PUT .../preview on an old server)
    put = client.put("/v1/agent/jobs/00000000-0000-0000-0000-000000000000/clips/1/nope", content=b"x")
    assert put.status_code == 404 and put.json()["code"] == "NOT_FOUND"
    assert client.post("/v1/no-such-thing").status_code == 404
    assert client.post("/jobs/123").status_code == 405  # pages are GET/HEAD only
