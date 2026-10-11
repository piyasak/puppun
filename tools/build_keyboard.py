"""Build punpun Thai input, the phone keyboard a live post types with (Q-44).

    .venv/Scripts/python tools/build_keyboard.py [--new-key]

keyboard/ holds its source: a GPL-2.0 fork of ADBKeyBoard (see keyboard/README.md). It is built with the
Android SDK already on the PC, without Gradle: aapt2 (resources + manifest) -> javac -> d8 -> zipalign ->
apksigner. Needs the SDK (ANDROID_HOME or %LOCALAPPDATA%/Android/Sdk) with build-tools 34.0.0 and
platforms/android-34, and a JDK 11+ (JAVA_HOME, else C:/Program Files/Java/jdk-14.0.1).

The signing key lives outside the repo (CLIPFLOW_KEYBOARD_KEYSTORE, default
%LOCALAPPDATA%/punpun-keys/keyboard.p12); its random password is stored next to it, encrypted for this
Windows user (DPAPI), and passed to the tools through the environment, never argv. --new-key makes the key
the first time; without it a missing key stops the build (a new key cannot update phones that have the
old one). Back the key up: phones only accept updates signed with it.

Output (var/ is never committed): var/dist/punpun-keyboard-<version>.apk (+ .sha256) and
punpun-keyboard-<version>-source.zip, the complete source to publish next to the APK (GPL-2.0 §3).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "keyboard"
WORK = ROOT / "var" / "build-keyboard"
OUT = ROOT / "var" / "dist"
VERSION_CODE, VERSION_NAME = 1, "1.0"
MIN_SDK, TARGET_SDK = 24, 36  # Play Protect blocked ADBKeyBoard (target 33) as built for an older Android
SDK = Path(os.environ.get("ANDROID_HOME") or Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk")
BUILD_TOOLS = SDK / "build-tools" / "34.0.0"
ANDROID_JAR = SDK / "platforms" / "android-34" / "android.jar"
JDK = Path(os.environ.get("JAVA_HOME") or "C:/Program Files/Java/jdk-14.0.1")
KEYSTORE = Path(os.environ.get("CLIPFLOW_KEYBOARD_KEYSTORE")
                or Path(os.environ.get("LOCALAPPDATA", "")) / "punpun-keys" / "keyboard.p12")
ALIAS = "punpun-keyboard"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*cmd, env=None) -> None:
    subprocess.run([str(c) for c in cmd], check=True, env={**os.environ, "JAVA_HOME": str(JDK), **(env or {})})


def tool(name: str) -> Path:
    for candidate in (BUILD_TOOLS / f"{name}.exe", BUILD_TOOLS / f"{name}.bat", BUILD_TOOLS / name):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"{name} not found in {BUILD_TOOLS}")


def key_password(new_key: bool) -> str:
    sys.path.insert(0, str(ROOT))
    from agent.credentials import _dpapi

    sealed = KEYSTORE.with_suffix(".pass.dpapi")
    if KEYSTORE.is_file() and sealed.is_file():
        return _dpapi(sealed.read_bytes(), protect=False).decode()
    if not new_key:
        raise SystemExit(f"no signing key at {KEYSTORE}; run with --new-key once (and back it up)")
    if KEYSTORE.exists():
        raise SystemExit(f"{KEYSTORE} exists without its password file; not replacing it")
    password = secrets.token_urlsafe(24)
    KEYSTORE.parent.mkdir(parents=True, exist_ok=True)
    run(JDK / "bin" / "keytool", "-genkeypair", "-keystore", KEYSTORE, "-storetype", "PKCS12", "-alias", ALIAS,
        "-keyalg", "RSA", "-keysize", "3072", "-validity", "10000", "-dname", "CN=punpun, O=punpun",
        "-storepass:env", "PUNPUN_KS_PASS", env={"PUNPUN_KS_PASS": password})
    sealed.write_bytes(_dpapi(password.encode(), protect=True))
    return password


def build(new_key: bool = False) -> dict:
    for need in (ANDROID_JAR, JDK / "bin" / "javac.exe"):
        if not need.is_file():
            raise SystemExit(f"missing {need}")
    password = key_password(new_key)
    shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "res").mkdir(parents=True)
    (WORK / "gen").mkdir()
    (WORK / "classes").mkdir()
    (WORK / "dex").mkdir()

    run(tool("aapt2"), "compile", "--dir", SRC / "res", "-o", WORK / "res.zip")
    unsigned = WORK / "unsigned.apk"
    run(tool("aapt2"), "link", "-o", unsigned, "-I", ANDROID_JAR, "--manifest", SRC / "AndroidManifest.xml",
        "--java", WORK / "gen", "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK,
        "--version-code", VERSION_CODE, "--version-name", VERSION_NAME, WORK / "res.zip")
    sources = [*SRC.rglob("*.java"), *(WORK / "gen").rglob("*.java")]
    run(JDK / "bin" / "javac", "-source", "8", "-target", "8", "-encoding", "UTF-8", "-Xlint:-options",
        "-bootclasspath", ANDROID_JAR, "-d", WORK / "classes", *sources)
    run(tool("d8"), "--release", "--min-api", MIN_SDK, "--lib", ANDROID_JAR, "--output", WORK / "dex",
        *sorted((WORK / "classes").rglob("*.class")))
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as apk:
        apk.write(WORK / "dex" / "classes.dex", "classes.dex")
    aligned = WORK / "aligned.apk"
    run(tool("zipalign"), "-f", "-p", "4", unsigned, aligned)

    OUT.mkdir(parents=True, exist_ok=True)
    final = OUT / f"punpun-keyboard-{VERSION_NAME}.apk"
    run(tool("apksigner"), "sign", "--ks", KEYSTORE, "--ks-key-alias", ALIAS, "--ks-pass", "env:PUNPUN_KS_PASS",
        "--out", final, aligned, env={"PUNPUN_KS_PASS": password})
    run(tool("apksigner"), "verify", final)
    digest = sha256(final)
    (OUT / f"{final.name}.sha256").write_text(f"{digest}  {final.name}\n", encoding="ascii")

    source = OUT / f"punpun-keyboard-{VERSION_NAME}-source.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(SRC.rglob("*")):
            if path.is_file():
                zf.write(path, f"punpun-keyboard/{path.relative_to(SRC).as_posix()}")
        zf.write(Path(__file__), "punpun-keyboard/build_keyboard.py")
    result = {"apk": str(final), "sha256": digest, "size_bytes": final.stat().st_size, "source": str(source),
              "version": VERSION_NAME, "target_sdk": TARGET_SDK}
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    build(new_key="--new-key" in sys.argv[1:])
