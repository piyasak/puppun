"""Agent POC CLI (PRD section I).

    python -m agent.cli devices
    python -m agent.cli doctor --serial <serial>
    python -m agent.cli dry-run --serial <serial> --file <clip.mp4> [--cleanup] [--no-power-saving]
    python -m agent.cli power --serial <serial> status|on|off

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

from agent.adb import Adb, AdbError, default_runner, is_wireless_serial
from agent.attempt import AttemptJournal, State
from agent.power import DeviceNotOnline, PowerSaver

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
    p_dry.add_argument("--no-power-saving", action="store_true", help="leave Wi-Fi and the app as they are")
    p_pow = sub.add_parser("power", help="phone Wi-Fi control used by power saving (Q-23)")
    p_pow.add_argument("--serial", required=True)
    p_pow.add_argument("action", choices=["status", "on", "off"])
    sub.add_parser("recover", help="after a crash: settle every unfinished attempt in the journal")
    args = parser.parse_args(argv)

    if args.cmd == "recover":
        return recover_all()

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
        if args.cmd == "power":
            return power_command(adb, args.serial, args.action)
        return dry_run(adb, args.serial, args.file, args.cleanup, power_saving=not args.no_power_saving)
    except AdbError as exc:
        print(f"adb error: {exc}")
        return 2


def recover_all() -> int:
    """Run on Agent start: unfinished attempts become RETRYABLE_FAILED or UNKNOWN (never resubmitted)."""
    journal = AttemptJournal(JOURNAL)
    ids = []
    if JOURNAL.exists():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            try:
                attempt_id = json.loads(line)["attempt_id"]
            except (json.JSONDecodeError, KeyError):
                continue
            if attempt_id not in ids:
                ids.append(attempt_id)
    results = {}
    for attempt_id in ids:
        before = journal.current(attempt_id)
        after = journal.recover(attempt_id)
        if before != after:
            results[attempt_id] = {"was": before, "now": after, "may_retry": journal.may_retry(attempt_id)}
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def power_command(adb: Adb, serial: str, action: str) -> int:
    if action == "on":
        adb.set_wifi(serial, True)
        adb.wait_wifi_online(serial)
    elif action == "off":
        if is_wireless_serial(serial):
            print("refused: ADB runs over Wi-Fi; switching Wi-Fi off would disconnect the Agent")
            return 1
        adb.set_wifi(serial, False)
    enabled, online = adb.wifi_state(serial)
    print(json.dumps({"wifi_enabled": enabled, "wifi_online": online}))
    return 0


def dry_run(adb: Adb, serial: str, clip: Path, cleanup: bool, power_saving: bool = True) -> int:
    report = adb.doctor(serial)
    if not report.ready:
        print(json.dumps({"ready": False, "problems": report.problems}, ensure_ascii=False))
        return 1
    adb.clean_staging(report.serial)  # leftovers of pushes interrupted by an earlier crash
    journal = AttemptJournal(JOURNAL)
    attempt_id = f"dryrun-{uuid.uuid4()}"
    journal.begin(attempt_id)
    saver = PowerSaver(adb, report.serial) if power_saving else None
    power = {"prepare": None, "release": None}
    result = {"attempt_id": attempt_id, "posted": False}
    try:
        if saver:
            try:
                power["prepare"] = asdict(saver.prepare())
            except DeviceNotOnline as exc:
                journal.advance(attempt_id, State.NEEDS_ACTION, str(exc))
                result["error"] = str(exc)
                return 1
        journal.advance(attempt_id, State.TRANSFERRING)
        try:
            remote = adb.push_verified(report.serial, clip)
        except AdbError as exc:
            journal.advance(attempt_id, State.RETRYABLE_FAILED, str(exc))
            result["error"] = f"transfer failed: {exc}"
            return 1
        journal.advance(attempt_id, State.PREPARING, remote)
        found = adb.scan_and_find(report.serial, remote)
        journal.advance(attempt_id, State.CANCELLED, "dry-run: stopped before submit")
        if cleanup:
            adb.shell(report.serial, f"rm -f '{remote}'")
        result.update(remote=remote, sha256_verified=True, gallery_found=found)
        return 0 if found else 1
    finally:
        # Close the app and switch Wi-Fi off only once the outcome is settled (agent/power.py).
        if saver:
            power["release"] = asdict(saver.release(journal.current(attempt_id)))
        result.update(state=journal.current(attempt_id), power=power)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.exit(main())
