"""Per-platform download cool-down after a bot check or rate limit (R-01).

When a platform answers with a bot check, retrying immediately makes the block
last longer. The Agent records the block and refuses further downloads from that
platform until the cool-down ends, doubling it on repeated blocks (1 h, 2 h, 4 h,
capped at 6 h) and resetting after a successful download. It never tries to get
around the check (no IP rotation, no proxy pools: PRD section O.2).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

BASE_S = 60 * 60
MAX_S = 6 * 60 * 60


class Cooldown:
    def __init__(self, path: Path, clock: Callable[[], float] = time.time, base_s: int = BASE_S, max_s: int = MAX_S):
        self.path = path
        self.clock = clock
        self.base_s = base_s
        self.max_s = max_s

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def remaining(self, platform: str) -> float:
        entry = self._load().get(platform)
        return max(0.0, entry["until"] - self.clock()) if entry else 0.0

    def record_block(self, platform: str) -> float:
        """Start (or extend) a cool-down; returns its length in seconds."""
        state = self._load()
        strikes = state.get(platform, {}).get("strikes", 0)
        wait = min(self.base_s * 2**strikes, self.max_s)
        state[platform] = {"until": self.clock() + wait, "strikes": strikes + 1}
        self._save(state)
        return wait

    def record_success(self, platform: str) -> None:
        state = self._load()
        if platform in state:
            del state[platform]
            self._save(state)
