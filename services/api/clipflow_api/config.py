"""Server configuration from the environment (PRD §M). Safe defaults: development, no secrets."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "development"
    database_url: str = ""
    web_origin: str = "http://localhost:5173"

    # Browser identity comes from Supabase Auth (E-25/E-27). Only the public project URL is
    # needed: access tokens are verified with the project's public signing keys (JWKS).
    supabase_url: str = ""
    supabase_jwt_audience: str = "authenticated"

    # Agent sign-in attempts per client address per minute (token guessing, PRD §14).
    agent_auth_rate_per_minute: int = 20

    @property
    def supabase_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str:
        return f"{self.supabase_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
