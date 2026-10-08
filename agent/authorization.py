"""One-time posting grants (Q-29). Without a grant there is no way to press Post.

A grant names a PO decision (e.g. "Q-29") and how many posts it allows. Using one is recorded and
fsynced *before* Post is pressed, so a crash right after counts as used and can never lead to an
extra post. The ledger lives under the Agent's data folder (var/, never committed). There is no
environment variable or setting that creates a grant: it is passed explicitly by the person running
the authorized command, and the decision it names must be recorded in docs/decisions.md.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


class GrantRefused(Exception):
    pass


@dataclass(frozen=True)
class PostGrant:
    decision: str
    number: int  # 1-based: which of the allowed posts this is


def take(ledger: Path, decision: str, allowed: int, note: str) -> PostGrant:
    if not decision or allowed < 1:
        raise GrantRefused("a grant needs a recorded decision and at least one allowed post")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else {}
    used = data.get(decision, {}).get("used", [])
    if len(used) >= allowed:
        raise GrantRefused(f"{decision} allowed {allowed} post(s) and all were used")
    used.append({"at": time.time(), "note": note[:200]})
    data[decision] = {"allowed": allowed, "used": used}
    tmp = ledger.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2))
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(ledger)
    return PostGrant(decision, len(used))
