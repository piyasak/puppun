"""Agent token format, hashing and verification (FR-12, NF-02, G2-02).

Format: `cfat_<prefix>_<secret>`. The prefix (10 chars, a-z0-9) is public and indexes the row;
the secret is 256 bits from the OS CSPRNG. The server stores only SHA-256 of the whole token
(a slow KDF adds nothing at 256 bits of entropy) and compares in constant time.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import string
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AgentToken, Membership, User

TOKEN_RE = re.compile(r"^cfat_([a-z0-9]{10})_([A-Za-z0-9_-]{43})$")
_ALPHABET = string.ascii_lowercase + string.digits


def generate() -> tuple[str, str, str]:
    """Return (token, prefix, sha256 hex). The token is shown once and never stored."""
    prefix = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    token = f"cfat_{prefix}_{secrets.token_urlsafe(32)}"
    return token, prefix, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def status(row: AgentToken, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= now:
        return "expired"
    return "active"


class TokenRejected(Exception):
    """One reason for every failure, so callers learn nothing about other accounts (T02)."""


@dataclass(frozen=True)
class AgentScope:
    token_id: object
    workspace_id: object
    environment_id: object  # always from the token row, never from the client (T05)


def verify(db: Session, username: str, token: str) -> AgentScope:
    """Check username + token for `/agent/authenticate` (P2.5). Raises TokenRejected."""
    m = TOKEN_RE.match(token or "")
    row = db.scalars(select(AgentToken).where(AgentToken.prefix == m.group(1))).first() if m else None
    # Compare against a dummy hash when the prefix is unknown, so both paths do the same work.
    expected = row.secret_hash if row else "0" * 64
    if not hmac.compare_digest(expected, hash_token(token or "")) or row is None:
        raise TokenRejected()
    if status(row) != "active":
        raise TokenRejected()
    owner = db.scalars(
        select(User.id)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workspace_id == row.workspace_id, User.username == (username or "").strip().lower())
    ).first()
    if owner is None:
        raise TokenRejected()
    return AgentScope(row.id, row.workspace_id, row.environment_id)
