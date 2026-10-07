"""Agent POC CLI (PRD section I).

    python -m agent.cli devices
    python -m agent.cli doctor --serial <serial>
    python -m agent.cli dry-run --serial <serial> --file <clip.mp4> [--cleanup] [--no-power-saving]
    python -m agent.cli power --serial <serial> status|on|off
    python -m agent.cli connect --server https://<host> --username <name> [--seconds N]
    python -m agent.cli register-devices --server https://<host> --username <name> [--serial S]

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
    p_con = sub.add_parser("connect", help="sign in to the server and send heartbeats (P2.5)")
    p_con.add_argument("--server", required=True)
    p_con.add_argument("--username", required=True)
    p_con.add_argument("--seconds", type=float, default=None, help="stop after N seconds (default: run until stopped)")
    p_con.add_argument("--data-dir", type=Path, default=None)
    p_con.add_argument("--no-phone-check", action="store_true", help="skip the phone check on start (Q-25)")
    p_reg = sub.add_parser("register-devices", help="register the ready phones on this PC with the server (P2.6)")
    p_reg.add_argument("--server", required=True)
    p_reg.add_argument("--username", required=True)
    p_reg.add_argument("--serial", default=None, help="only this phone (ADB or hardware serial)")
    p_reg.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.cmd == "recover":
        return recover_all()
    if args.cmd == "connect":
        return connect(args.server, args.username, args.seconds, args.data_dir, not args.no_phone_check)
    if args.cmd == "register-devices":
        return register_devices(args.server, args.username, args.serial, args.data_dir)

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


def connect(server: str, username: str, seconds: float | None, data_dir: Path | None,
            phone_check: bool = True) -> int:
    """The token comes from CLIPFLOW_AGENT_TOKEN or a hidden prompt, never from argv (visible to other
    processes). Windows Credential Manager storage arrives with the installer (P5)."""
    import getpass
    import os

    from agent.identity import AlreadyRunning, ProcessLock, default_data_dir, load_or_create_installation_id
    from agent.server_client import ServerClient, ServerError

    data_dir = data_dir or default_data_dir()
    token = os.environ.get("CLIPFLOW_AGENT_TOKEN") or getpass.getpass("Agent token: ")
    try:
        with ProcessLock(data_dir):
            installation_id = load_or_create_installation_id(data_dir)
            from agent.device_registry import DeviceSync
            from agent.server_client import run_connection

            # Q-25: on start, read the phones' serials, register new ones and say where to finish setup.
            sync = DeviceSync(lambda: Adb(default_runner())) if phone_check else None
            result = run_connection(ServerClient(server), username, token, installation_id, seconds, on_session=sync)
            print(json.dumps({"heartbeats": result.heartbeats, "stopped_because": result.stopped_because},
                             ensure_ascii=False))
            return 0 if result.stopped_because == "duration_elapsed" else 1
    except AlreadyRunning as exc:
        print(f"Agent is already running on this install: {exc}")
        return 3
    except ServerError as exc:
        print(f"server refused: {exc.code} — {exc.message}")
        return 2
    except (OSError, ValueError) as exc:
        print(f"cannot reach server: {exc}")
        return 2


def register_devices(server: str, username: str, only: str | None, data_dir: Path | None) -> int:
    """Sign in, register ready phones, report the state of all phones, sign out."""
    import getpass
    import os

    from agent.device_registry import discover, register_ready
    from agent.identity import AlreadyRunning, ProcessLock, default_data_dir, load_or_create_installation_id
    from agent.server_client import ServerClient, ServerError

    data_dir = data_dir or default_data_dir()
    token = os.environ.get("CLIPFLOW_AGENT_TOKEN") or getpass.getpass("Agent token: ")
    try:
        with ProcessLock(data_dir):
            client = ServerClient(server)
            session = client.authenticate(username, token, load_or_create_installation_id(data_dir))
            try:
                results = register_ready(client, session, discover(Adb(default_runner())), only)
            finally:
                client.end(session)
            print(json.dumps(results, ensure_ascii=False, indent=2))
            ok = {"REGISTERED", "ALREADY_REGISTERED"}
            return 0 if results and all(r["outcome"] in ok for r in results) else 1
    except AlreadyRunning as exc:
        print(f"Agent is already running on this install: {exc}")
        return 3
    except ServerError as exc:
        print(f"server refused: {exc.code} — {exc.message}")
        return 2
    except (OSError, ValueError, AdbError) as exc:
        print(f"error: {exc}")
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
