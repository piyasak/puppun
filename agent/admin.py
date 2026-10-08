"""Agent housekeeping commands: login/logout, status, install/update, rollback, local log (P5.1/P5.6)."""

from __future__ import annotations

import getpass
import json
import logging
import logging.handlers
import os
from pathlib import Path

from agent import __version__
from agent.identity import default_data_dir

log = logging.getLogger("punpun.agent")


def setup_logging(data_dir: Path) -> Path:
    """Local log with rotation (5 x 1 MB). Tokens are never logged: no code path passes one to it."""
    folder = data_dir / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "agent.log"
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in log.handlers):
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    log.info("agent %s starting", __version__)
    return path


def login(args) -> int:
    from agent.credentials import AgentConfig, CredentialError, save_config, save_token
    from agent.identity import load_or_create_installation_id
    from agent.server_client import ServerClient, ServerError

    data_dir = args.data_dir or default_data_dir()
    token = os.environ.get("CLIPFLOW_AGENT_TOKEN") or getpass.getpass("Agent token: ")
    client = ServerClient(args.server)
    try:
        session = client.authenticate(args.username, token, load_or_create_installation_id(data_dir))
    except ServerError as exc:
        print(f"server refused: {exc.code} — {exc.message}")
        return 2
    except (OSError, ValueError) as exc:
        print(f"cannot reach server: {exc}")
        return 2
    client.end(session)
    save_config(data_dir, AgentConfig(client.base, args.username))
    try:
        save_token(data_dir, token)
        stored = "encrypted for this Windows user"
    except CredentialError as exc:
        stored = f"not stored ({exc}); set CLIPFLOW_AGENT_TOKEN or type it at start"
    print(json.dumps({"server": client.base, "username": args.username, "environment": session.environment["name"],
                      "token": stored}, ensure_ascii=False, indent=2))
    return 0


def logout(args) -> int:
    from agent.credentials import forget_token

    forget_token(args.data_dir or default_data_dir())
    print("token removed from this PC")
    return 0


def status(args) -> int:
    from agent.credentials import load_config
    from agent.updater import default_install_dir, posts_in_flight, state

    data_dir = args.data_dir or default_data_dir()
    cfg = load_config(data_dir)
    inst = state(default_install_dir())
    phones = []
    try:
        from agent.adb import Adb, default_runner
        from agent.device_registry import discover

        phones = [{"serial": p.hw_serial, "state": p.state, "model": p.model} for p in discover(Adb(default_runner()))]
    except Exception as exc:  # noqa: BLE001 - status must always print
        phones = [{"error": str(exc)[:120]}]
    print(json.dumps({
        "version": __version__, "installed": {"current": inst.current, "previous": inst.previous},
        "server": cfg.server if cfg else None, "username": cfg.username if cfg else None,
        "token_stored": (data_dir / "token.bin").exists(),
        "installation_id": (data_dir / "installation_id").read_text(encoding="ascii").strip()
        if (data_dir / "installation_id").exists() else None,
        "phones": phones, "posts_in_flight": posts_in_flight(data_dir),
        "log": str(data_dir / "logs" / "agent.log"),
    }, ensure_ascii=False, indent=2))
    return 0


def install(args) -> int:
    from agent.updater import UpdateRefused, default_install_dir
    from agent.updater import install as do_install

    root = args.install_dir or default_install_dir()
    root.mkdir(parents=True, exist_ok=True)
    try:
        version = do_install(args.bundle, root, data_dir=args.data_dir or default_data_dir(), expected_sha256=args.sha256)
    except UpdateRefused as exc:
        print(f"update refused: {exc}")
        return 1
    print(json.dumps({"installed": version, "launcher": str(root / "punpun-agent.cmd")}, ensure_ascii=False))
    return 0


def rollback(args) -> int:
    from agent.updater import UpdateRefused, default_install_dir
    from agent.updater import rollback as do_rollback

    try:
        version = do_rollback(args.install_dir or default_install_dir(), data_dir=args.data_dir or default_data_dir())
    except UpdateRefused as exc:
        print(f"rollback refused: {exc}")
        return 1
    print(json.dumps({"current": version}, ensure_ascii=False))
    return 0
