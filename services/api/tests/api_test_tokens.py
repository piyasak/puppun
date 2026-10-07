"""Simulated Supabase access tokens for API tests.

A locally generated ES256 key signs tokens with the same claims shape as the real project
(role/aud/iss/sub/email/exp/iat/is_anonymous). This proves our verification logic only;
the live Supabase flow is checked separately (`test_supabase_live.py`, opt-in).
"""

from __future__ import annotations

import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import ec

SUPABASE_URL = "https://testproject.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def mint(sub: uuid.UUID | str, email: str | None, *, key=SIGNING_KEY, alg="ES256", **claims) -> str:
    now = int(time.time())
    payload = {
        "sub": str(sub), "email": email, "role": "authenticated", "aud": "authenticated",
        "iss": ISSUER, "iat": now, "exp": now + 3600, "is_anonymous": False,
    } | claims
    return jwt.encode({k: v for k, v in payload.items() if v is not None}, key, algorithm=alg,
                      headers={"kid": "test-key"})


def new_identity() -> tuple[uuid.UUID, str]:
    return uuid.uuid4(), f"user{uuid.uuid4().hex[:10]}@example.com"
