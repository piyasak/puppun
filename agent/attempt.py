"""Write-ahead publish-attempt journal for the Agent (FR-18, G1-04, PRD section H).

Each state change is appended and fsynced *before* the action it describes is
performed. If the Agent dies, recovery reads the last recorded state:

* stopped before SUBMITTING  -> RETRYABLE_FAILED (nothing can have been posted;
  the server still confirms no submission before retrying, T17)
* stopped at/after SUBMITTING -> UNKNOWN (the Post tap may have gone through;
  never retried automatically, T18)

Only a recorded human/support resolution with evidence moves UNKNOWN onward.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class State(StrEnum):
    CLAIMED = "CLAIMED"
    TRANSFERRING = "TRANSFERRING"
    PREPARING = "PREPARING"
    SUBMITTING = "SUBMITTING"
    VERIFYING = "VERIFYING"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    RETRYABLE_FAILED = "RETRYABLE_FAILED"
    UNKNOWN = "UNKNOWN"
    NEEDS_ACTION = "NEEDS_ACTION"
    CANCELLED = "CANCELLED"


PRE_SUBMIT = {State.CLAIMED, State.TRANSFERRING, State.PREPARING}
TERMINAL = {State.VERIFIED_SUCCESS, State.RETRYABLE_FAILED, State.NEEDS_ACTION, State.CANCELLED}

ALLOWED = {
    State.CLAIMED: {State.TRANSFERRING, State.RETRYABLE_FAILED, State.NEEDS_ACTION, State.CANCELLED},
    State.TRANSFERRING: {State.PREPARING, State.RETRYABLE_FAILED, State.NEEDS_ACTION, State.CANCELLED},
    State.PREPARING: {State.SUBMITTING, State.RETRYABLE_FAILED, State.NEEDS_ACTION, State.CANCELLED},
    State.SUBMITTING: {State.VERIFYING, State.UNKNOWN},
    State.VERIFYING: {State.VERIFIED_SUCCESS, State.UNKNOWN},
    State.UNKNOWN: set(),  # leaves only through resolve()
}

RESOLUTIONS = {
    "found_published": State.VERIFIED_SUCCESS,
    "confirmed_not_published": State.RETRYABLE_FAILED,
    "still_unknown": State.UNKNOWN,
}


class TransitionError(Exception):
    pass


@dataclass(frozen=True)
class Record:
    attempt_id: str
    state: State
    at: float
    detail: str = ""


class AttemptJournal:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, record: Record) -> None:
        line = json.dumps({"attempt_id": record.attempt_id, "state": record.state, "at": record.at, "detail": record.detail}, ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def history(self, attempt_id: str) -> list[Record]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn final line from a crash mid-write; earlier records are intact
            if data["attempt_id"] == attempt_id:
                out.append(Record(data["attempt_id"], State(data["state"]), data["at"], data.get("detail", "")))
        return out

    def current(self, attempt_id: str) -> State | None:
        history = self.history(attempt_id)
        return history[-1].state if history else None

    def begin(self, attempt_id: str) -> None:
        if self.current(attempt_id) is not None:
            raise TransitionError(f"attempt {attempt_id} already exists; a new attempt needs a new id")
        self._append(Record(attempt_id, State.CLAIMED, time.time()))

    def advance(self, attempt_id: str, new: State, detail: str = "") -> None:
        """Record intent to enter `new`. Call this before performing the step."""
        cur = self.current(attempt_id)
        if cur is None or new not in ALLOWED.get(cur, set()):
            raise TransitionError(f"{cur} -> {new} is not allowed")
        self._append(Record(attempt_id, new, time.time(), detail))

    def recover(self, attempt_id: str) -> State:
        """After a crash/disconnect, decide the safe state without touching the device."""
        cur = self.current(attempt_id)
        if cur is None or cur in TERMINAL or cur == State.UNKNOWN:
            return cur
        if cur in PRE_SUBMIT:
            self._append(Record(attempt_id, State.RETRYABLE_FAILED, time.time(), "recovered: stopped before submit"))
            return State.RETRYABLE_FAILED
        self._append(Record(attempt_id, State.UNKNOWN, time.time(), f"recovered: stopped during {cur}"))
        return State.UNKNOWN

    def may_retry(self, attempt_id: str) -> bool:
        return self.current(attempt_id) == State.RETRYABLE_FAILED

    def resolve(self, attempt_id: str, decision: str, evidence: str, actor: str) -> State:
        """Human/support resolution of an UNKNOWN attempt; evidence and actor are mandatory."""
        if self.current(attempt_id) != State.UNKNOWN:
            raise TransitionError("only UNKNOWN attempts are resolved")
        if decision not in RESOLUTIONS:
            raise TransitionError(f"decision must be one of {sorted(RESOLUTIONS)}")
        if not evidence.strip() or not actor.strip():
            raise TransitionError("resolution requires evidence and an actor")
        target = RESOLUTIONS[decision]
        if target != State.UNKNOWN:
            self._append(Record(attempt_id, target, time.time(), f"resolved by {actor}: {evidence}"))
        return target
