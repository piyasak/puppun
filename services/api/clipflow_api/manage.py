"""Server-side maintenance commands (E-46). Run on the server with DATABASE_URL set:

    python -m clipflow_api.manage grant-role --email someone@example.com --role admin|support|none
    python -m clipflow_api.manage retention [--dry-run]

Platform roles are granted only here, never through the API, and every change is audited.
"""

from __future__ import annotations

import argparse
import json
import sys

from sqlalchemy import func, select

from . import audit, retention
from .billing import now
from .config import get_settings
from .db import Database
from .models import User

ROLES = {"admin", "support", "none"}


def grant_role(db, email: str, role: str) -> int:
    users = db.scalars(select(User).where(func.lower(User.email) == email.lower())).all()
    if len(users) != 1:
        print(f"expected exactly one user with that email, found {len(users)}")
        return 1
    user = users[0]
    before, user.platform_role = user.platform_role, None if role == "none" else role
    audit.record(db, None, "platform_role.set", actor_user_id=None, target_id=user.id,
                 reason="granted with clipflow_api.manage on the server",
                 details={"before": before, "after": user.platform_role})
    db.commit()
    print(json.dumps({"user": user.username, "platform_role": user.platform_role}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clipflow_api.manage")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grant-role")
    g.add_argument("--email", required=True)
    g.add_argument("--role", required=True, choices=sorted(ROLES))
    r = sub.add_parser("retention")
    r.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    database = Database(settings.database_url, settings.db_schema)
    with database.sessionmaker() as db:
        if args.cmd == "grant-role":
            return grant_role(db, args.email, args.role)
        from .app import _storage

        result = retention.sweep(db, _storage(settings), now(), dry_run=args.dry_run)
        audit.record(db, None, "retention.sweep", reason="manage retention",
                     details={"deleted": len(result.deleted), "kept_in_use": len(result.kept_in_use),
                              "dry_run": args.dry_run})
        db.commit()
        print(json.dumps({"deleted": len(result.deleted), "kept_in_use": len(result.kept_in_use),
                          "dry_run": args.dry_run}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
