"""Agent POC CLI (PRD section I).

    python -m agent.cli devices
    python -m agent.cli doctor --serial <serial>
    python -m agent.cli dry-run --serial <serial> --file <clip.mp4> [--cleanup]

`dry-run` exercises transfer -> SHA-256 check -> Gallery discovery and records
every step in the attempt journal, then stops before any TikTok UI action. There
is deliberately no live-post command here (PRD section I).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

from agent.adb import Adb, AdbError, default_runner
from agent.attempt import AttemptJournal, State

JOURNAL = Path("var/agent/attempts.jsonl")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="agent.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    p_doc = sub.add_parser("doctor")
    p_doc.add_argument("--serial", required=True)
    p_dry = sub.add_parser("dry-run")
    p_dry.add_argument("--serial", required=True)
    p_dry.add_argument("--file", required=True, type=Path)
    p_dry.add_argument("--cleanup", action="store_true", help="delete the pushed test file afterwards")
    args = parser.parse_args(argv)

    try:
        adb = Adb(default_runner())
        if args.cmd == "devices":
            devices = adb.devices()
            print(json.dumps([asdict(d) | {"ready": d.ready} for d in devices], ensure_ascii=False, indent=2))
            return 0 if devices else 1
        if args.cmd == "doctor":
            report = adb.doctor(args.serial)
            print(json.dumps(asdict(report) | {"ready": report.ready}, ensure_ascii=False, indent=2))
            return 0 if report.ready else 1
        return dry_run(adb, args.serial, args.file, args.cleanup)
    except AdbError as exc:
        print(f"adb error: {exc}")
        return 2


def dry_run(adb: Adb, serial: str, clip: Path, cleanup: bool) -> int:
    report = adb.doctor(serial)
    if not report.ready:
        print(json.dumps({"ready": False, "problems": report.problems}, ensure_ascii=False))
        return 1
    journal = AttemptJournal(JOURNAL)
    attempt_id = f"dryrun-{uuid.uuid4()}"
    journal.begin(attempt_id)
    journal.advance(attempt_id, State.TRANSFERRING)
    try:
        remote = adb.push_verified(report.serial, clip)
    except AdbError as exc:
        journal.advance(attempt_id, State.RETRYABLE_FAILED, str(exc))
        print(f"transfer failed: {exc}")
        return 1
    journal.advance(attempt_id, State.PREPARING, remote)
    found = adb.scan_and_find(report.serial, remote)
    journal.advance(attempt_id, State.CANCELLED, "dry-run: stopped before submit")
    if cleanup:
        adb.shell(report.serial, f"rm -f '{remote}'")
    print(json.dumps({"attempt_id": attempt_id, "remote": remote, "sha256_verified": True,
                      "gallery_found": found, "posted": False}, ensure_ascii=False, indent=2))
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
