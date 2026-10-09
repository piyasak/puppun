"""Engine and session factory. One engine per database URL; tests point at a throwaway database."""

from __future__ import annotations

import re
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

SCHEMA_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def checked_schema(schema: str) -> str:
    if schema and not SCHEMA_RE.match(schema):
        raise RuntimeError(f"DB_SCHEMA must be a plain lower-case identifier, got {schema!r}")
    return schema


def driver_url(url: str) -> str:
    """Accept the URL as Supabase/hosting dashboards print it (postgres:// or postgresql://)."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url: str, schema: str = "") -> Engine:
    """`schema` (DB_SCHEMA) keeps every table out of `public`. On Supabase, `public` is published by
    its REST API to anyone holding the public key, so staging uses its own schema (E-49)."""
    if not url:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    engine = create_engine(driver_url(url), pool_pre_ping=True)
    if checked_schema(schema):
        @event.listens_for(engine, "connect")
        def _search_path(dbapi_conn, _record):
            with dbapi_conn.cursor() as cur:
                cur.execute(f'SET search_path TO "{schema}"')
            dbapi_conn.commit()
    return engine


class Database:
    def __init__(self, url: str, schema: str = ""):
        self.engine = make_engine(url, schema)
        self.sessionmaker = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Iterator[Session]:
        with self.sessionmaker() as db:
            yield db
