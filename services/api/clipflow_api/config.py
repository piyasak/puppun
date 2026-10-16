"""Server configuration from the environment (PRD §M). Safe defaults: development, no secrets."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "development"
    database_url: str = ""
    db_schema: str = ""  # own schema instead of public (Supabase staging, E-49); empty = default search_path
    web_origin: str = "http://localhost:5173"

    # Browser identity comes from Supabase Auth (E-25/E-27). Only the public project URL is
    # needed: access tokens are verified with the project's public signing keys (JWKS).
    supabase_url: str = ""
    supabase_jwt_audience: str = "authenticated"

    # Agent sign-in attempts per client address per minute (token guessing, PRD §14).
    agent_auth_rate_per_minute: int = 20

    # Clip storage (P3.2). With an endpoint set, S3/MinIO is used; otherwise files go under
    # `storage_dir` and previews are served by the API's signed /v1/media route.
    object_storage_endpoint: str = ""
    object_storage_bucket: str = "clipflow-media"
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_region: str = "us-east-1"  # Supabase Storage S3 needs the project's region
    storage_dir: str = "var/storage"
    public_api_base: str = "http://127.0.0.1:8000"  # how browsers reach this API (local-storage previews)
    media_signing_key: str = ""  # HMAC key for local preview links; random per process when empty
    preview_ttl_s: int = 300
    # Telegram notifications (Q-52). The bot token stays on the server (never sent to Agents or browsers);
    # without it nothing is sent. The webhook secret is checked on every update Telegram sends us.
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""
    notify_loop: bool = True  # the background sender; off in tests (they call notify.tick directly)
    max_clip_bytes: int = 512 * 1024 * 1024
    # Billing (P6, E-45). Only the sandbox provider exists until D06; it is refused when app_env is
    # "production". The secret signs/verifies sandbox webhooks; random per process when empty.
    billing_sandbox_secret: str = ""
    # D06 (PO 2026-10-10): "sandbox" (internal) or "stripe" (Checkout + webhooks, docs/runbooks/stripe.md).
    # Keys only from the environment; a live key is refused unless app_env is "production".
    billing_provider: str = "sandbox"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    # The Agent's double-click setup (E-50) offered on the Agents page. Hosting is the operator's
    # choice; the page shows the version, size and SHA-256 next to the link. Empty url = not offered.
    agent_setup_url: str = ""
    agent_setup_version: str = ""
    agent_setup_sha256: str = ""
    agent_setup_size_mb: str = ""  # text, so an empty dashboard value never stops the server
    # Which trial version new Workspaces get; None = the latest (production). Tests pin the original demo
    # trial (v1: 2 PCs / 2 sessions / 3 phones) that their limits were written against.
    default_plan_version: int | None = None
    # Built web app (apps/web/dist) to serve from this process, same origin as the API (staging image).
    web_dist: str = ""

    @property
    def supabase_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
