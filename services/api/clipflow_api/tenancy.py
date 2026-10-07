"""Tenant scoping in one place (architecture §2.2 rule 1).

Routes never query customer tables directly by id; they go through these helpers so the
`workspace_id` condition is part of every statement, not an after-the-fact check.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from .errors import not_found


def scoped[T](model: type[T], workspace_id: uuid.UUID) -> Select[tuple[T]]:
    return select(model).where(model.workspace_id == workspace_id)  # type: ignore[attr-defined]


def get_owned[T](db: Session, model: type[T], resource_id: uuid.UUID, workspace_id: uuid.UUID, *, for_update: bool = False) -> T:
    stmt = scoped(model, workspace_id).where(model.id == resource_id)  # type: ignore[attr-defined]
    if for_update:
        stmt = stmt.with_for_update()
    obj = db.scalars(stmt).first()
    if obj is None:
        raise not_found()
    return obj
