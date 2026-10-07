"""Unit tests for P1 worker logic. Real-source and real-render evidence lives in
docs/compatibility.md and var/poc manifests; these tests cover the rules only."""

import json

import pytest

from clipflow_worker import segments as seg
from clipflow_worker.media import duration_gaps
from clipflow_worker.render import ClipText, Template, build_ass
from clipflow_worker.source import (
    SourceError,
    SourceErrorCode,
    SourceInfo,
    _classify_download_error,
    assert_public_media_url,
    check_limits,
    classify_platform,
)
from clipflow_worker.textlayout import clusters, display_width, wrap


# --- source validation (FR-02, NF-03) ---------------------------------------

@pytest.mark.parametrize(
    "url, platform",
    [
        ("https://www.youtube.com/watch?v=BkwOfQCFxE8", "youtube"),
        ("https://youtu.be/BkwOfQCFxE8", "youtube"),
        ("https://www.bilibili.tv/th/video/4796693831489536?bstar_from=x", "bilibili"),
        ("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili"),
    ],
)
def test_supported_urls(url, platform):
    assert classify_platform(url) == platform


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=x",  # not https
        "https://evil.example.com/watch?v=x",
        "https://youtube.com.evil.example/watch",
        "https://user:pw@www.youtube.com/watch?v=x",
        "https://www.youtube.com:8443/watch?v=x",
        "https://127.0.0.1/video",
        "file:///etc/passwd",
    ],
)
def test_rejected_urls(url):
    with pytest.raises(SourceError) as err:
        classify_platform(url)
    assert err.value.code == SourceErrorCode.UNSUPPORTED_URL


@pytest.mark.parametrize("media_url", ["http://127.0.0.1/a.mp4", "http://10.0.0.5/a", "http://169.254.169.254/latest", "ftp://x/y"])
def test_media_url_ssrf_guard(media_url):
    with pytest.raises(SourceError):
        assert_public_media_url(media_url)


@pytest.mark.parametrize(
    "message, code",
    [
        ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", SourceErrorCode.NOT_ACCESSIBLE),
        ("ERROR: [youtube] x: Video unavailable", SourceErrorCode.NOT_FOUND),
        ("ERROR: Unsupported URL: https://x", SourceErrorCode.UNSUPPORTED_URL),
        ("ERROR: unable to download video data: HTTP Error 503", SourceErrorCode.DOWNLOADER_ERROR),
        ("ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate", SourceErrorCode.NOT_ACCESSIBLE),
        # Regression: "page" must not match an age marker; proxy failures are network errors.
        ("ERROR: [youtube] x: Unable to download API page: ('Unable to connect to proxy', "
         "OSError('Tunnel connection failed: 407 Proxy Authentication Required'))", SourceErrorCode.DOWNLOADER_ERROR),
        ("ERROR: [BiliIntl] x: Unable to download webpage: <urlopen error timed out>", SourceErrorCode.DOWNLOADER_ERROR),
    ],
)
def test_download_errors_are_distinguished(message, code):
    assert _classify_download_error(Exception(message)).code == code


def test_error_detail_has_no_ansi_codes():
    err = _classify_download_error(Exception("[0;31mERROR:[0m Video unavailable"))
    assert "" not in err.detail and err.code == SourceErrorCode.NOT_FOUND


def _probe(container, video, audio):
    return {"format": {"duration": container},
            "streams": [{"codec_type": "video", "duration": video}, {"codec_type": "audio", "duration": audio}]}


def test_duration_gaps_catches_truncated_file():
    # Real P1 case: a 230.7 s range came back as 33.4 s video / 29.7 s audio with no yt-dlp error.
    problems = duration_gaps(_probe("33.366666", "33.333333", "29.726500"), 230.725, 1.0)
    assert len(problems) == 3 and "expected 230.72s" in problems[0]
    assert duration_gaps(_probe("262.133333", "262.100000", "262.088000"), 262.088, 1.0) == []
    assert duration_gaps({"format": {}, "streams": []}, 10, 1.0) == ["container duration unknown"]


def _info(duration):
    return SourceInfo("youtube", "id", "u", "t", duration, None, None, None, None)


def test_limits_reject_unknown_and_too_long_duration():
    with pytest.raises(SourceError) as unknown:
        check_limits(_info(None))
    assert unknown.value.code == SourceErrorCode.LIMIT_EXCEEDED
    with pytest.raises(SourceError):
        check_limits(_info(3601), max_duration_s=3600)
    check_limits(_info(3600), max_duration_s=3600)


# --- segment selection (FR-04, FR-05, G3-02) ---------------------------------

SILENCE_LOG = "\n".join(
    f"[silencedetect @ 0x1] silence_start: {t}\n[silencedetect @ 0x1] silence_end: {t + 0.5} | silence_duration: 0.5"
    for t in range(0, 600, 7)
)


def test_parse_silencedetect():
    pauses = seg.parse_silencedetect(SILENCE_LOG)
    assert pauses[0] == (0.0, 0.5)
    assert len(pauses) == len(range(0, 600, 7))


def test_candidates_start_and_end_inside_pauses_within_limits():
    pauses = seg.parse_silencedetect(SILENCE_LOG)
    mids = {round((a + b) / 2, 3) for a, b in pauses}
    cands = seg.pause_candidates(pauses, 30, 60)
    assert cands
    for c in cands:
        assert 30 <= c.duration <= 60
        assert c.start in mids and c.end in mids


def test_selection_is_reproducible_and_non_overlapping():
    cands = seg.pause_candidates(seg.parse_silencedetect(SILENCE_LOG), 30, 60)
    a = seg.select(cands, 5, seed=42)
    b = seg.select(cands, 5, seed=42)
    c = seg.select(cands, 5, seed=43)
    assert a.segments == b.segments
    assert a.segments != c.segments
    ordered = a.segments
    assert all(x.end <= y.start for x, y in zip(ordered, ordered[1:]))


def test_insufficient_content_reports_fewer_clips_instead_of_reusing():
    pauses = [(0, 0.5), (40, 40.5), (80, 80.5)]  # room for at most two 40s clips
    sel = seg.select(seg.pause_candidates(pauses, 30, 60), 6, seed=1)
    assert len(sel.segments) == 2
    assert sel.insufficient


def test_json3_and_srt_parsing_and_retiming():
    j = json.dumps({"events": [
        {"tStartMs": 1000, "dDurationMs": 3000, "segs": [{"utf8": "สวัสดี"}, {"utf8": "ครับ"}]},
        {"tStartMs": 3500, "dDurationMs": 2000, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 3500, "dDurationMs": 2000, "segs": [{"utf8": "ต่อ"}]},
    ]})
    cues = seg.parse_json3(j)
    assert cues[0] == seg.Cue(1.0, 3.5, "สวัสดีครับ")  # overlap with next cue is clipped
    srt = "1\n00:00:01,000 --> 00:00:02,500\nบรรทัด\nสอง\n\n2\n00:00:03,000 --> 00:00:04,000\nสาม\n"
    assert seg.parse_srt(srt)[0] == seg.Cue(1.0, 2.5, "บรรทัด สอง")
    inside = seg.cues_within(cues, seg.Segment(2.0, 4.0, "x"))
    assert inside[0] == seg.Cue(0.0, 1.5, "สวัสดีครับ")


# --- Thai text layout (FR-07, G3-03) ------------------------------------------

def test_clusters_keep_marks_and_leading_vowels_attached():
    assert clusters("ที่") == ["ที่"]
    assert clusters("เขา") == ["เข", "า"]
    assert display_width("น้ำ") == 2  # น้ + ำ


def test_wrap_respects_width_without_orphans():
    text = "สูนซิงแกกล้าจับฉันเหรอไม่มีทีมออกแบบของ"
    lines = wrap(text, 26)
    assert all(display_width(l) <= 26 for l in lines)
    assert min(display_width(l) for l in lines) >= 10
    assert "".join(lines) == text


def test_wrap_truncates_to_max_lines():
    lines = wrap("ก" * 200, 20, max_lines=3)
    assert len(lines) == 3 and lines[-1].endswith("…")


def test_ass_contains_title_ending_and_subs_in_their_time_ranges():
    text = ClipText("ชื่อเรื่อง {x}", "ติดตามตอนต่อไป", [seg.Cue(0.5, 2.0, "ซับ"), seg.Cue(9.0, 10.0, "ถูกตัด")])
    ass = build_ass(text, 10.0, Template(ending_seconds=2.5))
    assert "Dialogue: 1,0:00:00.00,0:00:07.50,Title,,0,0,0,,ชื่อเรื่อง (x)" in ass  # braces escaped
    assert "Dialogue: 2,0:00:07.50,0:00:10.00,Ending" in ass
    assert "ซับ" in ass and "ถูกตัด" not in ass  # subtitles never overlap the ending card
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    no_subs = build_ass(text, 10.0, Template(burn_subtitles=False))
    assert "ซับ" not in no_subs and "ชื่อเรื่อง" in no_subs
