"""R-01 cool-down, bot-check classification and customer-provided files (Q-17).

The local-file tests generate tiny videos with ffmpeg; they are skipped where
ffmpeg is not installed. They check validation logic, not platform behaviour.
"""

import subprocess

import pytest

from clipflow_worker.cooldown import Cooldown
from clipflow_worker.local_source import inspect_local, sha256_file, sidecar_captions
from clipflow_worker.poc import guarded, main
from clipflow_worker.source import SourceError, SourceErrorCode, _classify_download_error

# --- bot check / rate limit classification ----------------------------------

@pytest.mark.parametrize(
    "message",
    [
        # Real message seen 2026-10-07 (note the curly apostrophe).
        "ERROR: [youtube] PBES5k67dhI: Sign in to confirm you’re not a bot. Use --cookies-from-browser",
        "ERROR: [youtube] x: Sign in to confirm you're not a bot",
        "ERROR: unable to download video data: HTTP Error 429: Too Many Requests",
    ],
)
def test_bot_check_is_rate_limited_not_private(message):
    assert _classify_download_error(Exception(message)).code == SourceErrorCode.RATE_LIMITED


def test_format_limit_uses_short_side_so_vertical_sources_keep_resolution():
    from clipflow_worker.source import format_options

    opts = format_options(1080)
    assert opts["format_sort"] == ["res:1080"]  # res = smaller dimension in yt-dlp
    assert "height<=" not in opts["format"]  # regression: height filter picked 480x852 for 720x1280


def test_private_video_still_not_accessible():
    err = _classify_download_error(Exception("ERROR: [youtube] x: Private video. Sign in if you've been granted access"))
    assert err.code == SourceErrorCode.NOT_ACCESSIBLE


# --- cool-down ------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def test_cooldown_backs_off_caps_resets_and_persists(tmp_path):
    clock = Clock()
    path = tmp_path / "cooldown.json"
    cd = Cooldown(path, clock)
    assert cd.remaining("youtube") == 0
    assert [cd.record_block("youtube") for _ in range(5)] == [3600, 7200, 14400, 21600, 21600]
    assert Cooldown(path, clock).remaining("youtube") == 21600  # survives an Agent restart
    assert cd.remaining("bilibili") == 0  # per platform
    clock.now += 21600
    assert cd.remaining("youtube") == 0
    cd.record_success("youtube")
    assert cd.record_block("youtube") == 3600  # strikes reset after a success


def test_guarded_blocks_during_cooldown_and_records_new_blocks(tmp_path):
    clock = Clock()
    cd = Cooldown(tmp_path / "c.json", clock)
    url = "https://www.youtube.com/watch?v=x"

    def bot_check():
        raise SourceError(SourceErrorCode.RATE_LIMITED, "Sign in to confirm you’re not a bot")

    with pytest.raises(SourceError) as first:
        guarded(cd, url, bot_check)
    assert "paused 60 min" in first.value.detail

    calls = []
    with pytest.raises(SourceError) as second:
        guarded(cd, url, lambda: calls.append(1))
    assert second.value.code == SourceErrorCode.RATE_LIMITED and calls == []  # no request sent

    clock.now += 3600
    assert guarded(cd, url, lambda: "ok") == "ok"
    assert cd.remaining("youtube") == 0


def test_other_errors_do_not_start_a_cooldown(tmp_path):
    cd = Cooldown(tmp_path / "c.json", Clock())

    def private():
        raise SourceError(SourceErrorCode.NOT_ACCESSIBLE, "Private video")

    with pytest.raises(SourceError):
        guarded(cd, "https://www.youtube.com/watch?v=x", private)
    assert cd.remaining("youtube") == 0


# --- customer-provided files ------------------------------------------------------

def _ffmpeg():
    from clipflow_worker.media import binary

    try:
        return binary("ffmpeg")
    except FileNotFoundError:
        pytest.skip("ffmpeg not installed")


def _make_video(path, seconds=3):
    subprocess.run(
        [_ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x240:rate=10:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=duration={seconds}", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", str(path)],
        check=True,
    )
    return path


def test_local_video_is_identified_by_content_hash(tmp_path):
    video = _make_video(tmp_path / "my clip.mp4")
    info = inspect_local(video)
    assert info.platform == "local" and info.extractor == "local-file"
    assert info.source_id == sha256_file(video)
    assert info.duration_s == 3 and (info.width, info.height) == (320, 240)
    assert info.url == "" and info.title == "my clip"  # no local path stored
    copy = tmp_path / "renamed.mp4"
    copy.write_bytes(video.read_bytes())
    assert inspect_local(copy).source_id == info.source_id


def test_local_file_rejections(tmp_path):
    with pytest.raises(SourceError) as missing:
        inspect_local(tmp_path / "nope.mp4")
    assert missing.value.code == SourceErrorCode.NOT_FOUND

    with pytest.raises(SourceError) as folder:
        inspect_local(tmp_path)
    assert folder.value.code == SourceErrorCode.UNSUPPORTED_FILE

    _ffmpeg()
    fake = tmp_path / "fake.mp4"
    fake.write_text("not a video", encoding="utf-8")  # extension is not trusted
    with pytest.raises(SourceError) as not_video:
        inspect_local(fake)
    assert not_video.value.code == SourceErrorCode.UNSUPPORTED_FILE

    video = _make_video(tmp_path / "v.mp4")
    with pytest.raises(SourceError) as too_big:
        inspect_local(video, max_filesize=10)
    assert too_big.value.code == SourceErrorCode.LIMIT_EXCEEDED


def test_sidecar_captions(tmp_path):
    video = tmp_path / "ep1.mp4"
    video.write_bytes(b"")
    assert sidecar_captions(video) is None
    (tmp_path / "ep1.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nสวัสดี\n", encoding="utf-8")
    assert sidecar_captions(video) == tmp_path / "ep1.srt"


@pytest.mark.parametrize("argv", [["produce"], ["produce", "https://www.youtube.com/watch?v=x", "--file", "a.mp4"]])
def test_produce_needs_exactly_one_source(argv):
    with pytest.raises(SystemExit):
        main(argv)
