"""Agent POC CLI (PRD section I).

    python -m agent.cli devices
    python -m agent.cli doctor --serial <serial>
    python -m agent.cli dry-run --serial <serial> --file <clip.mp4> [--cleanup] [--no-power-saving]
    python -m agent.cli power --serial <serial> status|on|off
    python -m agent.cli connect --server https://<host> --username <name> [--seconds N] [--media-dir D] [--no-jobs]
    python -m agent.cli register-devices --server https://<host> --username <name> [--serial S]
    python -m agent.cli ui-rehearsal --serial <serial> --file <clip.mp4> --caption <text> --account <handle>

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
    sub.add_parser("version", help="print the Agent version")
    sub.add_parser("licenses", help="third-party software in this Agent and where its licences are")
    p_set = sub.add_parser("settings", help="settings window: pairing code, clips/videos folders, start with Windows")
    p_set.add_argument("--server", default="https://punpun-staging.onrender.com", help="used until one is saved")
    p_set.add_argument("--data-dir", type=Path, default=None)
    p_pair = sub.add_parser("pair", help="link this PC with a pairing code from the web (no token to copy)")
    p_pair.add_argument("--server", required=True)
    p_pair.add_argument("--code", required=True, help="the XXXX-XXXX code from the Agents page (10 minutes, once)")
    p_pair.add_argument("--data-dir", type=Path, default=None)
    p_login = sub.add_parser("login", help="save server, username and the Agent token (encrypted for this Windows user)")
    p_login.add_argument("--server", required=True)
    p_login.add_argument("--username", required=True)
    p_login.add_argument("--data-dir", type=Path, default=None)
    p_login.add_argument("--clips-dir", type=Path, default=None,
                         help="where finished clips are kept on this PC (asked when not given; Q-33)")
    p_fold = sub.add_parser("set-folder", help="change where finished clips are kept on this PC (Q-33)")
    p_fold.add_argument("folder", type=Path)
    p_fold.add_argument("--move", action="store_true", help="also move the clips already made")
    p_fold.add_argument("--data-dir", type=Path, default=None)
    p_out = sub.add_parser("logout", help="forget the stored Agent token")
    p_out.add_argument("--data-dir", type=Path, default=None)
    p_st = sub.add_parser("status", help="Agent version, settings, phones and posts in progress")
    p_st.add_argument("--data-dir", type=Path, default=None)
    p_inst = sub.add_parser("install", help="install/update from a bundle (refused while a post is being submitted)")
    p_inst.add_argument("--bundle", required=True, type=Path)
    p_inst.add_argument("--sha256", default=None, help="published SHA-256 of the bundle")
    p_inst.add_argument("--install-dir", type=Path, default=None)
    p_inst.add_argument("--data-dir", type=Path, default=None)
    p_rb = sub.add_parser("rollback", help="go back to the previous installed version")
    p_rb.add_argument("--install-dir", type=Path, default=None)
    p_rb.add_argument("--data-dir", type=Path, default=None)
    p_con = sub.add_parser("connect", help="sign in to the server and send heartbeats (P2.5)")
    p_con.add_argument("--server", default=None, help="default: saved by `login`")
    p_con.add_argument("--username", default=None, help="default: saved by `login`")
    p_con.add_argument("--seconds", type=float, default=None, help="stop after N seconds (default: run until stopped)")
    p_con.add_argument("--data-dir", type=Path, default=None)
    p_con.add_argument("--no-phone-check", action="store_true", help="skip the phone check on start (Q-25)")
    p_con.add_argument("--media-dir", type=Path, default=None,
                       help="folder with the customer's own video files for local-file jobs (Q-17)")
    p_con.add_argument("--no-jobs", action="store_true", help="do not claim clip jobs (P3.3)")
    p_con.add_argument("--no-posts", action="store_true", help="do not take scheduled posts (P5, dry-run only)")
    p_con.add_argument("--ui-rehearsal", action="store_true",
                       help="in dry runs also check the account and type the caption in TikTok, then close it (Q-27)")
    p_ui = sub.add_parser("ui-rehearsal", help="TikTok steps up to Post on the QA phone, then close (P5.4, Q-27)")
    p_ui.add_argument("--serial", required=True)
    p_ui.add_argument("--file", required=True, type=Path)
    p_ui.add_argument("--caption", required=True)
    p_ui.add_argument("--account", required=True, help="expected TikTok handle on this phone")
    p_reg = sub.add_parser("register-devices", help="register the ready phones on this PC with the server (P2.6)")
    p_reg.add_argument("--server", required=True)
    p_reg.add_argument("--username", required=True)
    p_reg.add_argument("--serial", default=None, help="only this phone (ADB or hardware serial)")
    p_reg.add_argument("--data-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.cmd == "version":
        from agent import __version__

        print(__version__)
        return 0
    if args.cmd == "settings":
        from agent.settings_gui import run

        return run(args.data_dir, args.server)
    if args.cmd == "pair":
        from agent import settings
        from agent.identity import default_data_dir

        try:
            result = settings.pair(args.data_dir or default_data_dir(), args.server, args.code)
        except settings.SettingsError as exc:
            print(f"เชื่อมต่อไม่สำเร็จ: {exc}")
            return 2
        print(json.dumps(result | {"token": "encrypted for this Windows user"}, ensure_ascii=False))
        return 0
    if args.cmd == "licenses":
        from agent.adb import bundled_adb

        own = bundled_adb()
        print(json.dumps({"adb": {
            "what": "Android SDK Platform-Tools adb (unmodified), Copyright The Android Open Source Project",
            "licence": str(own.with_name("LICENSE.txt")) if own else None,
            "notice": str(own.with_name("NOTICE.txt")) if own else None,
            "readme": str(own.with_name("README.txt")) if own else None,
            "bundled": own is not None}}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd in ("login", "logout", "status", "install", "rollback", "set-folder"):
        from agent import admin

        return getattr(admin, args.cmd.replace("-", "_"))(args)
    if args.cmd == "recover":
        return recover_all()
    if args.cmd == "connect":
        return connect(args.server, args.username, args.seconds, args.data_dir, not args.no_phone_check,
                       None if args.no_jobs else (args.media_dir or saved_media_dir(args.data_dir) or Path.cwd()),
                       posts=not args.no_posts,
                       ui_rehearsal=args.ui_rehearsal)
    if args.cmd == "register-devices":
        return register_devices(args.server, args.username, args.serial, args.data_dir)

    try:
        adb = Adb(default_runner())
        if args.cmd == "devices":
            devices = adb.devices()
            print(json.dumps([asdict(d) | {"ready": d.ready} for d in devices], ensure_ascii=False, indent=2))
            return 0 if devices else 1
        if args.cmd == "doctor":
            from agent.adb import adb_report

            report = adb.doctor(args.serial)
            print(json.dumps(asdict(report) | {"ready": report.ready, "adb": adb_report()}, ensure_ascii=False, indent=2))
            return 0 if report.ready else 1
        if args.cmd == "power":
            return power_command(adb, args.serial, args.action)
        if args.cmd == "ui-rehearsal":
            return ui_rehearsal(adb, args.serial, args.file, args.caption, args.account)
        return dry_run(adb, args.serial, args.file, args.cleanup, power_saving=not args.no_power_saving)
    except AdbError as exc:
        print(f"adb error: {exc}")
        return 2


def saved_media_dir(data_dir: Path | None) -> Path | None:
    """The videos folder chosen in the settings window, when it still exists."""
    from agent.credentials import load_config
    from agent.identity import default_data_dir

    cfg = load_config(data_dir or default_data_dir())
    return Path(cfg.media_dir) if cfg and cfg.media_dir and Path(cfg.media_dir).is_dir() else None


def connect(server: str, username: str, seconds: float | None, data_dir: Path | None,
            phone_check: bool = True, media_dir: Path | None = None, posts: bool = True,
            ui_rehearsal: bool = False) -> int:
    """The token comes from CLIPFLOW_AGENT_TOKEN or a hidden prompt, never from argv (visible to other
    processes). Windows Credential Manager storage arrives with the installer (P5)."""
    import getpass
    import os

    from agent.admin import setup_logging
    from agent.credentials import CredentialError, load_config, load_token
    from agent.identity import AlreadyRunning, ProcessLock, default_data_dir, load_or_create_installation_id
    from agent.server_client import ServerClient, ServerError

    data_dir = data_dir or default_data_dir()
    saved = load_config(data_dir)
    server = server or (saved.server if saved else None)
    username = username or (saved.username if saved else None)
    if not server or not username:
        print("run `login` first, or pass --server and --username")
        return 2
    try:
        stored = load_token(data_dir)
    except CredentialError:
        stored = None
    token = os.environ.get("CLIPFLOW_AGENT_TOKEN") or stored or getpass.getpass("Agent token: ")
    setup_logging(data_dir)
    try:
        with ProcessLock(data_dir):
            installation_id = load_or_create_installation_id(data_dir)
            from agent.adb import find_adb, start_server
            from agent.device_registry import DeviceSync
            from agent.server_client import run_connection

            if exe := find_adb():
                start_server(exe)  # one daemon start before the phone check and post threads use adb
            # Q-25: on start, read the phones' serials, register new ones and say where to finish setup.
            sync = DeviceSync(lambda: Adb(default_runner())) if phone_check else None
            # P3.3: claim clip jobs and make them on this PC (one at a time).
            from agent.job_runner import JobRunner
            from agent.post_runner import PostRunner

            workers = [JobRunner(data_dir, media_dir)] if media_dir else []
            if posts:  # P5: scheduled posts, dry-run only (the server refuses Submit, E-40)
                workers.append(PostRunner(data_dir, lambda: Adb(default_runner()), ui_rehearsal=ui_rehearsal))
            result = run_connection(ServerClient(server), username, token, installation_id, seconds,
                                    on_session=sync, worker=workers)
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


def ui_rehearsal(adb: Adb, serial: str, clip: Path, caption: str, account: str) -> int:
    """Everything a post needs in TikTok except pressing Post; TikTok is closed at the end (Q-27).

    Prints the account read on the phone, whether visibility and caption were set exactly, and where
    the screenshot of the ready-but-not-posted screen was saved (var/, never committed)."""
    from agent.tiktok_ui import TikTokUi, UiStop, media_id

    report = adb.doctor(serial)
    if not report.ready:
        print(json.dumps({"ready": False, "problems": report.problems}, ensure_ascii=False))
        return 1
    ui = TikTokUi(adb, report.serial)
    remote = None
    result: dict = {"stopped_before_post": True}
    try:
        remote = adb.push_verified(report.serial, clip, remote_name=f"cf_rehearsal_{uuid.uuid4().hex[:8]}.mp4")
        if not adb.scan_and_find(report.serial, remote):
            result["error"] = "GALLERY_NOT_FOUND"
            return 1
        found = media_id(adb, report.serial, remote.rsplit("/", 1)[-1])
        result["account"] = ui.check_account(account)
        ui.open_post_screen(found)
        ui.set_only_me()
        ui.type_caption(caption)
        result.update(visibility="only_you", caption_exact=True)
        shot = Path("var/evidence/phone") / f"ui_rehearsal_{uuid.uuid4().hex[:8]}.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        adb._run(["-s", report.serial, "pull", ui.screenshot(), str(shot)])
        result["screenshot"] = str(shot)
        return 0
    except UiStop as exc:
        result.update(error=exc.code, detail=exc.detail)
        return 1
    finally:
        ui.close()  # TikTok is stopped: nothing is posted or kept
        if remote:
            adb.shell(report.serial, f"rm -f '{remote}' /sdcard/cf_check.png /sdcard/cf_ui.xml")
            adb.shell(report.serial, f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d 'file://{remote}'")
        print(json.dumps(result, ensure_ascii=False, indent=2))


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
