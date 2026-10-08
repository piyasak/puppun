"""Audit trail helper. Callers pass ids and an action name only, never secrets or request bodies."""

from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditEvent


def record(
    db: Session,
    request: Request,
    action: str,
    *,
    workspace_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    reason: str | None = None,
    details: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            target_id=target_id,
            request_id=getattr(request.state, "request_id", None) if request is not None else None,
            reason=reason,
            details=details,
        )
    )
