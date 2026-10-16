"""FastAPI application factory.

Run locally: `uvicorn clipflow_api.app:app --reload` with DATABASE_URL and SUPABASE_URL set (see .env.example).
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import errors
from .config import Settings, get_settings
from .db import Database
from .errors import ApiError
from .identity import KeyResolver, SupabaseVerifier, jwks_resolver
from .ratelimit import SlidingWindow
from .routers import (
    admin,
    agent,
    agent_tokens,
    agents,
    auth,
    billing,
    clips,
    devices,
    environments,
    jobs,
    library,
    pairing,
    posts,
    schedules,
    ui_profile,
)
from .storage import LocalStorage, S3Storage, Storage

log = logging.getLogger("clipflow.api")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _storage(settings: Settings) -> Storage:
    if settings.object_storage_endpoint:
        return S3Storage(settings.object_storage_endpoint, settings.object_storage_bucket,
                         settings.object_storage_access_key, settings.object_storage_secret_key,
                         region=settings.object_storage_region)
    key = settings.media_signing_key.encode() or secrets.token_bytes(32)
    return LocalStorage(Path(settings.storage_dir), settings.public_api_base, key)


def create_app(settings: Settings | None = None, *, resolve_key: KeyResolver | None = None,
               storage: Storage | None = None, posting_mode: str = "dry_run") -> FastAPI:
    """`posting_mode` is "dry_run" for every running server: Agents stop before Submit and the
    server refuses SUBMITTING. "live" exists only so tests can drive the post-Submit state machine
    with simulated Agents; no setting or env value can turn it on (PRD §C/§I, E-40)."""
    if posting_mode not in ("dry_run", "live"):
        raise ValueError("posting_mode must be dry_run or live")
    settings = settings or get_settings()
    app = FastAPI(title="ClipFlow API", version="0.1.0")
    app.state.settings = settings
    app.state.posting_mode = posting_mode
    app.state.db = Database(settings.database_url, settings.db_schema)
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
    app.include_router(pairing.web_router)
    app.include_router(pairing.agent_router)
    app.include_router(agents.router)
    app.include_router(agent.router)
    app.include_router(devices.agent_router)
    app.include_router(devices.web_router)
    app.include_router(jobs.web_router)
    app.include_router(jobs.agent_router)
    app.include_router(library.agent_router)
    app.include_router(library.web_router)
    app.include_router(clips.web_router)
    app.include_router(clips.agent_router)
    app.include_router(clips.agent_files_router)
    app.include_router(clips.media_router)
    app.include_router(schedules.web_router)
    app.include_router(schedules.items_router)
    app.include_router(posts.agent_router)
    app.include_router(billing.router)
    app.include_router(admin.router)
    app.include_router(ui_profile.admin_router)
    app.include_router(ui_profile.agent_router)

    # Which release answers: BUILD_ID from the image build, else the commit Render deployed.
    build = os.environ.get("BUILD_ID") or os.environ.get("RENDER_GIT_COMMIT", "")[:7] or "dev"

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "build": build}

    if settings.web_dist:
        _serve_web(app, Path(settings.web_dist))
    return app


def _serve_web(app: FastAPI, dist: Path) -> None:
    """The built web app on the same origin (staging image): hashed assets cached for a year, every
    other non-API path answers index.html so client routes work on reload. API paths keep their 404."""
    index = dist / "index.html"
    if not index.is_file():
        raise RuntimeError(f"WEB_DIST has no index.html: {dist}")
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    root_files = {p.name for p in dist.iterdir() if p.is_file() and p.name != "index.html"}

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def web(path: str, request: Request):
        if path.startswith(("v1/", "assets/")) or path in ("v1", "healthz"):
            raise ApiError(404, "NOT_FOUND", "ไม่พบหน้านี้")  # any method: a missing endpoint is not a 405
        if request.method not in ("GET", "HEAD"):
            raise ApiError(405, "METHOD_NOT_ALLOWED", "ไม่รองรับคำขอนี้")
        if path in root_files:
            return FileResponse(dist / path)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def __getattr__(name: str):
    # `uvicorn clipflow_api.app:app` builds the app lazily so importing this module needs no DB.
    if name == "app":
        return create_app()
    raise AttributeError(name)
