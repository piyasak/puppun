"""Agent settings and the stored Agent token (P5.1).

- `config.json` in the data folder holds the server URL and username (not secret).
- The Agent token is encrypted with Windows DPAPI for the current Windows user (CryptProtectData)
  and kept as `token.bin`. Another Windows user, or a copy of the file on another PC, cannot
  decrypt it. The token is never written in plain text, printed, or put in a URL or log.
- Off Windows (development, CI) nothing is stored: the token comes from CLIPFLOW_AGENT_TOKEN or
  a prompt, as before.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path

ENTROPY = b"punpun-agent-token-v1"  # binds the blob to this use; not a secret


class CredentialError(Exception):
    pass


@dataclass
class AgentConfig:
    server: str
    username: str


def save_config(data_dir: Path, config: AgentConfig) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = data_dir / "config.json.tmp"
    tmp.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, data_dir / "config.json")


def load_config(data_dir: Path) -> AgentConfig | None:
    try:
        data = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
        return AgentConfig(data["server"], data["username"])
    except (FileNotFoundError, KeyError, ValueError):
        return None


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _dpapi(data: bytes, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise CredentialError("secure token storage is only available on Windows")
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    out = _Blob()
    source, entropy = _blob(data), _blob(ENTROPY)
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(source), None, ctypes.byref(entropy), None, None, 0x1, ctypes.byref(out))  # UI forbidden
    if not ok:
        raise CredentialError("Windows could not protect/unprotect the token (DPAPI)")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def save_token(data_dir: Path, token: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp = data_dir / "token.bin.tmp"
    tmp.write_bytes(_dpapi(token.encode("utf-8"), protect=True))
    os.replace(tmp, data_dir / "token.bin")


def load_token(data_dir: Path) -> str | None:
    path = data_dir / "token.bin"
    if not path.exists():
        return None
    return _dpapi(path.read_bytes(), protect=False).decode("utf-8")


def forget_token(data_dir: Path) -> None:
    (data_dir / "token.bin").unlink(missing_ok=True)
