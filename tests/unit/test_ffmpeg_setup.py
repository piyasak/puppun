"""FFmpeg installed on request (PO 2026-10-12): checked download, only the named files, then found."""

from __future__ import annotations

import hashlib
import io
import zipfile
from types import SimpleNamespace

import pytest

from agent import ffmpeg_setup
from agent.ffmpeg_setup import FfmpegError

INSIDE = ffmpeg_setup.INSIDE


def archive(extra=None, drop=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for inside in ffmpeg_setup.FILES:
            if inside != drop:
                zf.writestr(inside, b"exe" if inside.endswith(".exe") else b"text")
        zf.writestr(f"{INSIDE}/bin/ffplay.exe", b"not wanted")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener(data):
    return lambda url, timeout: Response(data)


def good_run(cmd, **kw):
    return SimpleNamespace(returncode=0, stdout="ffmpeg version 9.0.2 --enable-gpl --enable-libass --enable-libx264")


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(ffmpeg_setup, "found", lambda: None)
    return tmp_path / "ClipFlowAgent" / "ffmpeg"


def pin(monkeypatch, data):
    monkeypatch.setattr(ffmpeg_setup, "ZIP_SHA256", hashlib.sha256(data).hexdigest())


def test_installs_only_the_named_files_after_the_hash_check(home, monkeypatch):
    data = archive(extra={"../../evil.exe": b"x"})
    pin(monkeypatch, data)
    seen = []
    assert ffmpeg_setup.install(opener(data), progress=lambda got, total: seen.append(got), run=good_run) == "installed"
    assert sorted(p.name for p in home.iterdir()) == ["LICENSE.txt", "README.txt", "ffmpeg.exe", "ffprobe.exe"]
    assert seen and not (home.parent / "ffmpeg-download.part").exists()
    assert not (home.parent.parent / "evil.exe").exists()


def test_a_different_file_is_never_installed(home, monkeypatch):
    pin(monkeypatch, b"the checked one")
    with pytest.raises(FfmpegError, match="ไม่ตรง"):
        ffmpeg_setup.install(opener(archive()), run=good_run)
    assert not home.exists() and not (home.parent / "ffmpeg-download.part").exists()


def test_a_build_without_libass_is_refused(home, monkeypatch):
    data = archive()
    pin(monkeypatch, data)

    def bare(cmd, **kw):
        return SimpleNamespace(returncode=0, stdout="ffmpeg version 9.0.2 --enable-libx264")

    with pytest.raises(FfmpegError, match="libass"):
        ffmpeg_setup.install(opener(data), run=bare)
    assert not home.exists()


def test_already_there_downloads_nothing(monkeypatch):
    monkeypatch.setattr(ffmpeg_setup, "found", lambda: "C:/ffmpeg/bin/ffmpeg.exe")

    def never(url, timeout):
        raise AssertionError("no download when FFmpeg is there")

    assert ffmpeg_setup.install(never) == "present"


def test_the_installed_copy_is_where_the_worker_looks(tmp_path, monkeypatch):
    from clipflow_worker import media

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("FFMPEG_DIR", raising=False)
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    with pytest.raises(FileNotFoundError):
        media.binary("ffmpeg")
    ffmpeg_setup.folder().mkdir(parents=True)
    (ffmpeg_setup.folder() / "ffmpeg.exe").write_bytes(b"exe")
    assert media.binary("ffmpeg").endswith("ffmpeg.exe")
