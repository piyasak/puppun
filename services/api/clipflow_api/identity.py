"""Verify Supabase Auth access tokens (browser identity, E-27).

Supabase signs access tokens with an asymmetric project key (ES256 on this project) and
publishes the public keys at `<project>/auth/v1/.well-known/jwks.json`. The API only ever
holds public keys; the Supabase service-role key is never needed here.

Every failure maps to one generic error, so callers cannot tell an expired token from a
forged one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

import jwt

# Asymmetric only: accepting HS256 would let a public key be misused as an HMAC secret.
ALGORITHMS = ["ES256", "RS256"]

KeyResolver = Callable[[str], object]  # token -> verification key


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    user_id: uuid.UUID  # Supabase auth user id (`sub`); also our users.id
    email: str


def jwks_resolver(jwks_url: str) -> KeyResolver:
    client = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=600, timeout=10)

    def resolve(token: str):
        return client.get_signing_key_from_jwt(token).key

    return resolve


class SupabaseVerifier:
    def __init__(self, resolve_key: KeyResolver, issuer: str, audience: str):
        self._resolve_key, self._issuer, self._audience = resolve_key, issuer, audience

    def verify(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in ALGORITHMS:
                raise InvalidToken("algorithm not allowed")
            claims = jwt.decode(
                token,
                self._resolve_key(token),
                algorithms=ALGORITHMS,
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
                leeway=30,
            )
        except InvalidToken:
            raise
        except Exception as exc:  # noqa: BLE001 - any decode/key failure is the same 401
            raise InvalidToken(type(exc).__name__) from None
        if claims.get("role") != "authenticated" or claims.get("is_anonymous"):
            raise InvalidToken("not a signed-in user")
        email = (claims.get("email") or "").lower()
        if not email:
            raise InvalidToken("no email")
        try:
            return Identity(uuid.UUID(claims["sub"]), email)
        except ValueError:
            raise InvalidToken("bad subject") from None
