"""FastAPI application factory.

Run locally: `uvicorn clipflow_api.app:app --reload` with DATABASE_URL and SUPABASE_URL set (see .env.example).
"""

from __future__ import annotations

import logging
import re
import secrets
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import errors
from .config import Settings, get_settings
from .db import Database
from .identity import KeyResolver, SupabaseVerifier, jwks_resolver
from .ratelimit import SlidingWindow
from .routers import agent, agent_tokens, agents, auth, clips, devices, environments, jobs
from .storage import LocalStorage, S3Storage, Storage

log = logging.getLogger("clipflow.api")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _storage(settings: Settings) -> Storage:
    if settings.object_storage_endpoint:
        return S3Storage(settings.object_storage_endpoint, settings.object_storage_bucket,
                         settings.object_storage_access_key, settings.object_storage_secret_key)
    key = settings.media_signing_key.encode() or secrets.token_bytes(32)
    return LocalStorage(Path(settings.storage_dir), settings.public_api_base, key)


def create_app(settings: Settings | None = None, *, resolve_key: KeyResolver | None = None,
               storage: Storage | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="ClipFlow API", version="0.1.0")
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.storage = storage or _storage(settings)
    if resolve_key is None:
        if not settings.supabase_url:
            raise RuntimeError("SUPABASE_URL is not set (see .env.example)")
        resolve_key = jwks_resolver(settings.supabase_jwks_url)
    app.state.agent_auth_limiter = SlidingWindow(limit=settings.agent_auth_rate_per_minute, window_s=60)
    app.state.verifier = SupabaseVerifier(resolve_key, settings.supabase_issuer, settings.supabase_jwt_audience)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=False,  # bearer tokens, no cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        # Correlation id for logs and error bodies (NF-08). Only method, path, status and timing
        # are logged: never query strings, bodies or headers (Authorization holds the access token).
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        request.state.request_id = rid
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log.info("request_id=%s %s %s %s %.0fms", rid, request.method, request.url.path, response.status_code,
                 (time.perf_counter() - started) * 1000)
        return response

    errors.install(app)
    app.include_router(auth.router)
    app.include_router(environments.router)
    app.include_router(agent_tokens.router)
    app.include_router(agents.router)
    app.include_router(agent.router)
    app.include_router(devices.agent_router)
    app.include_router(devices.web_router)
    app.include_router(jobs.web_router)
    app.include_router(jobs.agent_router)
    app.include_router(clips.web_router)
    app.include_router(clips.agent_router)
    app.include_router(clips.media_router)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


def __getattr__(name: str):
    # `uvicorn clipflow_api.app:app` builds the app lazily so importing this module needs no DB.
    if name == "app":
        return create_app()
    raise AttributeError(name)
