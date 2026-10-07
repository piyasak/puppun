"""P1 feasibility CLI: inspect sources and produce N vertical clips from one source.

    python -m clipflow_worker.poc inspect <url> [<url> ...]
    python -m clipflow_worker.poc produce <url> --clips 3 --seed 42 --out var/poc
    python -m clipflow_worker.poc produce --file <video the customer downloaded> [--captions x.srt]

`produce` downloads only the selected time ranges (not the whole source), renders
each clip, and writes manifest.json with the seed, intervals, template version,
render hashes, media probe results and timings used for G1-02 / G1-06 evidence.
Title/Ending/Caption/Hashtag come from a fixed Thai template in the POC; AI text
generation is not part of P1 until Q-02 is decided.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError, download_range_func

from clipflow_worker import segments as seg
from clipflow_worker.media import binary, duration_gaps, ensure_on_path, probe
from clipflow_worker.render import ClipText, RenderError, Template, render_clip
from clipflow_worker.source import (
    SourceError,
    SourceErrorCode,
    DEFAULT_MAX_DURATION_S,
    SourceInfo,
    _base_opts,
    _classify_download_error,
    check_limits,
    classify_platform,
    format_options,
    inspect,
)
from clipflow_worker.cooldown import Cooldown
from clipflow_worker.local_source import inspect_local, sidecar_captions

COOLDOWN_FILE = Path("var/agent/source_cooldown.json")


def fetch_captions(url: str, info: SourceInfo, dest: Path) -> Path | None:
    """Download uploaded subtitles, else original-language auto captions (never translations)."""
    langs = info.subtitle_langs or info.auto_caption_langs
    if not langs:
        return None
    lang = langs[0]
    opts = {
        **_base_opts(),
        "skip_download": True,
        "writesubtitles": bool(info.subtitle_langs),
        "writeautomaticsub": not info.subtitle_langs,
        "subtitleslangs": [lang],
        "subtitlesformat": "json3/srt/best",
        "outtmpl": str(dest / "captions.%(ext)s"),
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except DownloadError as exc:
        raise _classify_download_error(exc) from exc
    found = sorted(p for p in dest.glob("captions.*") if p.suffix in (".json3", ".srt"))
    return found[0] if found else None


def _ffmpeg_audio_log(audio: Path, audio_filter: str) -> str:
    result = subprocess.run(
        [binary("ffmpeg"), "-hide_banner", "-nostats", "-i", str(audio), "-af", audio_filter, "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    return result.stderr


def detect_pauses(url: str, dest: Path, duration_s: int) -> tuple[list[tuple[float, float]], int]:
    """Download the smallest audio-only rendition, then find pauses in it."""
    opts = {**_base_opts(), "format": "wa/ba", "outtmpl": str(dest / "audio.%(ext)s")}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except DownloadError as exc:
        raise _classify_download_error(exc) from exc
    audio = next(p for p in dest.glob("audio.*") if p.suffix not in (".part", ".ytdl"))
    return analyze_pauses(audio, duration_s)


def analyze_pauses(
    media: Path, duration_s: int, min_pause: float = 0.3, target_spacing_s: float = 20.0
) -> tuple[list[tuple[float, float]], int]:
    """Find pauses with silencedetect in any local file that has audio.

    Sources with music under the dialogue have no true silence, so the threshold
    starts strict (-35 dB) and relaxes in 5 dB steps until there is on average one
    pause per `target_spacing_s`, but never closer than 3 dB to the mean loudness.
    Returns the pauses and the threshold used (stored in the manifest).
    """
    audio = media
    mean = re.search(r"mean_volume: (-?[\d.]+) dB", _ffmpeg_audio_log(audio, "volumedetect"))
    ceiling = int(float(mean.group(1)) - 3) if mean else -20
    pauses: list[tuple[float, float]] = []
    used_db = noise_db = -35
    while noise_db <= ceiling:
        used_db = noise_db
        pauses = seg.parse_silencedetect(_ffmpeg_audio_log(audio, f"silencedetect=noise={noise_db}dB:d={min_pause}"))
        if len(pauses) * target_spacing_s >= duration_s:
            break
        noise_db += 5
    return pauses, used_db


RANGE_TOLERANCE_S = 1.0  # force_keyframes_at_cuts lands within ~0.05 s in P1 runs


def download_range(url: str, start: float, end: float, dest: Path, max_height: int, attempts: int = 2) -> Path:
    """Download [start, end) and verify its length; retry a truncated download once (bounded, FR-03)."""
    problems: list[str] = []
    for _ in range(attempts):
        path = _download_range_once(url, start, end, dest, max_height)
        problems = duration_gaps(probe(path), end - start, RANGE_TOLERANCE_S)
        if not problems:
            return path
        path.unlink(missing_ok=True)
    raise SourceError(
        SourceErrorCode.DOWNLOADER_ERROR,
        f"incomplete range download {start:.1f}-{end:.1f}s after {attempts} attempts: " + "; ".join(problems),
    )


def _download_range_once(url: str, start: float, end: float, dest: Path, max_height: int) -> Path:
    out = dest / f"range_{int(start * 1000)}"
    opts = {
        **_base_opts(),
        **format_options(max_height),
        "merge_output_format": "mp4",
        "download_ranges": download_range_func(None, [(start, end)]),
        "force_keyframes_at_cuts": True,
        "ffmpeg_location": ensure_on_path(),
        "outtmpl": str(out) + ".%(ext)s",
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
    except DownloadError as exc:
        raise _classify_download_error(exc) from exc
    path = out.with_suffix(".mp4")
    if not path.exists():
        raise SourceError(SourceErrorCode.DOWNLOADER_ERROR, "range download produced no mp4")
    return path


def clip_text(source_title: str, index: int, total: int) -> tuple[ClipText, dict]:
    short = source_title.split("|")[0].strip()
    text = ClipText(title=short, ending=f"ติดตามตอนต่อไป ({index}/{total})")
    metadata = {
        "version": 1,
        "title": short,
        "ending": text.ending,
        "caption": f"{short} — ตอนที่ {index}/{total}",
        "hashtags": ["#คลิปสั้น", "#ตอนต่อไป"],
        "generator": "poc-fixed-template",
    }
    return text, metadata


def produce(args: argparse.Namespace) -> dict:
    out_root = Path(args.out)
    t0 = time.perf_counter()
    local = Path(args.file) if args.file else None
    if local:
        info = inspect_local(local)
    else:
        info = inspect(args.url)
    check_limits(info, args.max_duration)
    job_dir = out_root / f"{info.platform}_{info.source_id[:16]}_seed{args.seed}"
    work = job_dir / "work"
    work.mkdir(parents=True, exist_ok=True)

    if local:
        captions = Path(args.captions) if args.captions else sidecar_captions(local)
        pauses, noise_db = analyze_pauses(local, info.duration_s)
    else:
        captions = fetch_captions(args.url, info, work)
        pauses, noise_db = detect_pauses(args.url, work, info.duration_s)
    cues = seg.load_cues(captions) if captions else []
    candidates = seg.pause_candidates(pauses, args.min_len, args.max_len)
    if not candidates:
        candidates = seg.time_candidates(info.duration_s, args.min_len, args.max_len)
    selection = seg.select(candidates, args.clips, args.seed)
    t_select = time.perf_counter()

    tpl = Template(burn_subtitles=not args.no_subtitles)
    clips = []
    for index, segment in enumerate(selection.segments, start=1):
        c0 = time.perf_counter()
        if local:
            part, offset = local, segment.start  # cut straight from the customer's file
        else:
            part, offset = download_range(args.url, segment.start, segment.end, work, args.max_height), 0.0
        c1 = time.perf_counter()
        text, metadata = clip_text(info.title, index, len(selection.segments))
        text.subtitles = seg.cues_within(cues, segment)
        result = render_clip(part, offset, segment.duration, text, job_dir / f"clip_{index:02d}.mp4", tpl)
        c2 = time.perf_counter()
        clips.append({
            "index": index,
            "source_interval": segment.to_dict(),
            "subtitle_cues": len(text.subtitles),
            "metadata": metadata,
            "render": {**asdict(result), "path": result.path.name},
            "timing_s": {"download": round(c1 - c0, 2), "render": round(c2 - c1, 2)},
        })

    manifest = {
        "source": {**info.to_dict(), **({"file_name": local.name} if local else {})},
        "rights_declaration": (
            "Customer-provided file; rights accepted once at signup (Q-14) — POC"
            if local else "Declared authorized by workspace owner in chat on 2026-10-06 (P1 test corpus)"
        ),
        "selection": {
            "seed": selection.seed,
            "version": selection.version,
            "requested": selection.requested,
            "produced": len(selection.segments),
            "insufficient_content": selection.insufficient,
            "candidates": selection.candidates,
            "method": selection.segments[0].method if selection.segments else None,
            "caption_track": captions.name if captions else None,
            "audio_pauses": len(pauses),
            "silence_threshold_db": noise_db,
        },
        "template_version": tpl.version,
        "burn_subtitles": tpl.burn_subtitles,
        "clips": clips,
        "timing_s": {"inspect_and_select": round(t_select - t0, 2), "total": round(time.perf_counter() - t0, 2)},
    }
    (job_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def guarded(cooldown: Cooldown, url: str, action):
    """Run a network action unless the platform is cooling down after a bot check (R-01)."""
    platform = classify_platform(url)
    wait = cooldown.remaining(platform)
    if wait > 0:
        raise SourceError(SourceErrorCode.RATE_LIMITED, f"{platform} is cooling down after a bot check; retry in {wait / 60:.0f} min")
    try:
        result = action()
    except SourceError as exc:
        if exc.code == SourceErrorCode.RATE_LIMITED:
            wait = cooldown.record_block(platform)
            exc.detail = f"{exc.detail} — paused {wait / 60:.0f} min before the next {platform} download"
        raise
    cooldown.record_success(platform)
    return result


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="clipflow_worker.poc")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("urls", nargs="+")
    p_produce = sub.add_parser("produce")
    p_produce.add_argument("url", nargs="?", help="YouTube/Bilibili link; omit when using --file")
    p_produce.add_argument("--file", help="video the customer downloaded themselves (Q-17)")
    p_produce.add_argument("--captions", help="optional .srt for --file (default: <video>.srt if present)")
    p_produce.add_argument("--clips", type=int, default=3)
    p_produce.add_argument("--seed", type=int, default=42)
    p_produce.add_argument("--min-len", type=float, default=180)  # D02: 3-5 minute clips
    p_produce.add_argument("--max-len", type=float, default=300)
    p_produce.add_argument("--max-duration", type=int, default=DEFAULT_MAX_DURATION_S)
    p_produce.add_argument("--max-height", type=int, default=1080)
    p_produce.add_argument("--out", default="var/poc")
    p_produce.add_argument("--no-subtitles", action="store_true", help="do not burn captions (source already has hard subs)")
    args = parser.parse_args(argv)
    if args.cmd == "produce" and bool(args.url) == bool(args.file):
        parser.error("produce needs exactly one of: a URL or --file")
    # Before any yt-dlp call: yt-dlp caches ffmpeg detection per process.
    ensure_on_path()
    cooldown = Cooldown(COOLDOWN_FILE)

    if args.cmd == "inspect":
        failures = 0
        for url in args.urls:
            try:
                info = guarded(cooldown, url, lambda: inspect(url))
                print(json.dumps({"ok": True, **info.to_dict()}, ensure_ascii=False))
            except SourceError as exc:
                failures += 1
                print(json.dumps({"ok": False, "url": url, "code": exc.code, "detail": exc.detail[:300]}, ensure_ascii=False))
        return 1 if failures else 0

    try:
        manifest = produce(args) if args.file else guarded(cooldown, args.url, lambda: produce(args))
    except SourceError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "detail": exc.detail[:300]}, ensure_ascii=False))
        return 1
    except RenderError as exc:
        print(json.dumps({"ok": False, "code": "RENDER_MISMATCH", "detail": str(exc)[:300]}, ensure_ascii=False))
        return 1
    sel = manifest["selection"]
    print(f"produced {sel['produced']}/{sel['requested']} clips (seed {sel['seed']}, {sel['method']})")
    for clip in manifest["clips"]:
        r = clip["render"]
        print(f"  {r['path']}: {r['width']}x{r['height']} {r['duration_s']:.1f}s {r['video_codec']}/{r['audio_codec']} subs={clip["subtitle_cues"] if manifest["burn_subtitles"] else "off"}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
