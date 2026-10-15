"""T08 / G3-01: source downloads never reach private addresses, redirects included; renders are bounded.

Real sockets and real yt-dlp networking against two local HTTP servers: A plays the part of a
public media host (allowed by the test policy), B is an internal service. A redirects to B.
"""

from __future__ import annotations

import subprocess
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yt_dlp
from yt_dlp.utils import DownloadError

from clipflow_worker.media import binary
from clipflow_worker.netguard import BlockedAddress, public_only
from clipflow_worker.render import ENCODER_THREADS, ClipText, RenderError, RenderLimits, Template, render_clip
from clipflow_worker.source import (
    SourceError,
    SourceErrorCode,
    _base_opts,
    _classify_download_error,
    assert_public_media_url,
)


class _Server:
    def __init__(self, redirect_to: str | None = None):
        hits = self.hits = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server API
                hits.append(self.path)
                if redirect_to:
                    self.send_response(302)
                    self.send_header("Location", redirect_to)
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"internal secret")

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def internal():
    server = _Server()
    yield server
    server.close()


@pytest.fixture
def redirector(internal):
    server = _Server(redirect_to=f"http://127.0.0.1:{internal.port}/latest/meta-data/video.mp4")
    yield server
    server.close()


def only_port(port):
    """Test policy: treat exactly one local port as the 'public' host, everything else stays blocked."""
    return lambda host, p, address: p == port


def test_guard_blocks_private_addresses_only_inside_the_block(internal):
    url = f"http://127.0.0.1:{internal.port}/"
    with public_only(), pytest.raises(urllib.error.URLError) as err:
        urllib.request.urlopen(url, timeout=5)
    assert isinstance(err.value.reason, BlockedAddress)
    assert internal.hits == []  # refused before connecting
    # Outside the block (e.g. the Agent talking to its own local server) nothing changes.
    assert urllib.request.urlopen(url, timeout=5).read() == b"internal secret"


def test_guard_is_per_thread(internal):
    url = f"http://127.0.0.1:{internal.port}/"
    other = {}

    def heartbeat_thread():
        other["body"] = urllib.request.urlopen(url, timeout=5).read()

    with public_only():
        t = threading.Thread(target=heartbeat_thread)
        t.start()
        t.join()
        with pytest.raises(urllib.error.URLError) as err:
            urllib.request.urlopen(url, timeout=5)
        assert isinstance(err.value.reason, BlockedAddress)
    assert other["body"] == b"internal secret"


def test_redirect_to_internal_address_is_refused_through_yt_dlp(redirector, internal):  # T08
    url = f"http://127.0.0.1:{redirector.port}/video.mp4"
    with (public_only(allow=only_port(redirector.port)), pytest.raises(DownloadError) as err,
          yt_dlp.YoutubeDL({**_base_opts(), "skip_download": True}) as ydl):
        ydl.extract_info(url, download=False)
    assert redirector.hits == ["/video.mp4"]  # the allowed host was asked...
    assert internal.hits == []  # ...but the redirect target was never contacted
    classified = _classify_download_error(err.value)
    assert classified.code == SourceErrorCode.BLOCKED_ADDRESS
    assert "127.0.0.1" not in classified.detail  # users see the refusal, not internal addresses


@pytest.mark.parametrize("media_url", ["http://127.0.0.1/a.mp4", "http://10.0.0.5/a", "http://169.254.169.254/latest",
                                       "http://localhost/x", "http://[::1]/x", "ftp://x/y"])
def test_media_urls_for_ffmpeg_are_checked_first(media_url):
    with pytest.raises(SourceError) as err:
        assert_public_media_url(media_url)
    assert err.value.code == SourceErrorCode.BLOCKED_ADDRESS


def _video(path: Path, seconds: int) -> Path:
    subprocess.run([binary("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=640x360:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=duration={seconds}", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


def test_render_that_runs_too_long_is_stopped(tmp_path):
    src = _video(tmp_path / "src.mp4", 6)
    out = tmp_path / "clip.mp4"
    limits = RenderLimits(min_timeout_s=0.05, seconds_per_clip_second=0.0)
    with pytest.raises(RenderError, match="was stopped"):
        render_clip(src, 0, 5, ClipText("ชื่อ", "จบ"), out, Template(), limits)
    assert not out.exists()  # no half-written clip is left for upload


def test_render_uses_capped_threads(tmp_path, monkeypatch):
    src = _video(tmp_path / "src.mp4", 3)
    seen = {}
    real_run = subprocess.run

    def spy(cmd, **kw):
        if "libx264" in cmd and "-filter_complex" in cmd:
            seen["cmd"], seen["kw"] = cmd, kw
        return real_run(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    result = render_clip(src, 0, 2, ClipText("ชื่อ", "จบ"), tmp_path / "c.mp4", Template(), RenderLimits(threads=1))
    assert result.width == 1080 and result.height == 1920
    cmd = seen["cmd"]
    assert cmd[cmd.index("-filter_complex_threads") + 1] == "1"
    assert cmd[cmd.index("-threads") + 1] == str(ENCODER_THREADS)  # fixed: x264's output depends on it
    assert seen["kw"]["timeout"] == 120.0


def test_pipeline_runs_linked_sources_under_the_guard(internal, monkeypatch, tmp_path):
    """pipeline.plan (used by the Agent job runner and the POC CLI) guards every network step."""
    from clipflow_worker import pipeline

    def inspect_that_lands_on_internal(url):
        try:
            with yt_dlp.YoutubeDL({**_base_opts(), "skip_download": True}) as ydl:
                ydl.extract_info(f"http://127.0.0.1:{internal.port}/meta-data", download=False)
        except DownloadError as exc:
            raise _classify_download_error(exc) from exc

    monkeypatch.setattr(pipeline, "inspect", inspect_that_lands_on_internal)
    with pytest.raises(SourceError) as err:
        pipeline.plan(work=tmp_path, count=1, seed=1, min_len=15, max_len=25,
                      url="https://www.youtube.com/watch?v=PBES5k67dhI")
    assert err.value.code == SourceErrorCode.BLOCKED_ADDRESS
    assert internal.hits == []
