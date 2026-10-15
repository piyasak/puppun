"""Render one 9:16 clip with Title, Ending and subtitles burned in (FR-06, FR-07).

All text is drawn by libass from a generated .ass file (libass shapes Thai via
HarfBuzz). Lines are pre-wrapped by textlayout so nothing overflows the frame.
The template version and a hash of the output are returned so a clip can record
exactly which render it is (PRD section F).
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from clipflow_worker.media import binary, duration_gaps, probe
from clipflow_worker.segments import Cue
from clipflow_worker.textlayout import wrap

WIDTH, HEIGHT, FPS = 1080, 1920, 30
DURATION_TOLERANCE_S = 0.5
# Approvals and schedule items are bound to the render's sha256 (PRD section F/H), so a remake of
# the same segment must be the same file on any PC. x264's output depends on its own thread count,
# so the encoder always gets this many threads whatever the CPU; filters and decoding are
# bit-exact for any count and still follow RenderLimits.
ENCODER_THREADS = 4

# FFmpeg picks SIMD code by the CPU, and its AAC encoder (float) rounds differently with
# AVX/AVX2/FMA; on x86-64 it is held to SSE2, which every x86-64 CPU has (forcing a level the CPU
# lacks would crash; ~10% slower on a 60 s clip). x264's cpu-independent mode uses the same
# algorithms on every CPU: its own SIMD choice gave different video on Intel and AMD, and on
# AVX-512 CPUs different video from one render to the next. Checked on 12 CI runners (5 CPU
# models, AVX2 and AVX-512): one file. No measurable cost.
CPU_ARGS = ("-cpuflags", "mmx+mmxext+sse+sse2+cmov") if platform.machine().lower() in ("amd64", "x86_64") else ()
X264_ARGS = ("-x264-params", "cpu-independent=1")
# No metadata from the source (creation time, location, chapters) and no version strings from the
# muxer: only the frames and samples decide the bytes.
BITEXACT_ARGS = ("-map_metadata", "-1", "-map_chapters", "-1", "-fflags", "+bitexact",
                 "-flags:v", "+bitexact", "-flags:a", "+bitexact")


class RenderError(Exception):
    """The rendered file does not match the requested clip (e.g. truncated input)."""


@dataclass(frozen=True)
class Template:
    version: str = "tpl-default-v2"
    font: str = "Leelawadee UI"
    # Height reserved at the top for the Title. The source picture is fitted below it,
    # so burned-in text never covers source content, credits or watermarks.
    title_band: int = 320
    title_size: int = 66
    title_chars: int = 22
    title_lines: int = 2
    burn_subtitles: bool = True
    sub_size: int = 54
    sub_chars: int = 26
    ending_size: int = 76
    ending_chars: int = 18
    ending_seconds: float = 2.5


@dataclass(frozen=True)
class RenderLimits:
    """Resource limits for one render on the customer's PC (NF-03, G3-01, E-38).

    Filters get at most half of the CPU threads (the x264 encoder always ENCODER_THREADS) and
    the render runs below normal priority on Windows, so posting, the browser and the Agent's
    heartbeats stay responsive. A render that takes longer than `seconds_per_clip_second` x clip
    length (plus a floor) is killed.
    """

    threads: int = max(1, (os.cpu_count() or 2) // 2)
    seconds_per_clip_second: float = 4.0
    min_timeout_s: float = 120.0
    low_priority: bool = True

    def timeout_for(self, duration_s: float) -> float:
        return max(self.min_timeout_s, duration_s * self.seconds_per_clip_second)


def _priority_flags(limits: RenderLimits) -> int:
    if limits.low_priority and sys.platform == "win32":
        return subprocess.BELOW_NORMAL_PRIORITY_CLASS
    return 0


@dataclass
class ClipText:
    title: str
    ending: str
    subtitles: list[Cue] = field(default_factory=list)


@dataclass
class RenderResult:
    path: Path
    sha256: str
    width: int
    height: int
    duration_s: float
    video_codec: str
    audio_codec: str | None
    template_version: str


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def _lines(text: str, width: int, max_lines: int) -> str:
    return r"\N".join(_escape(line) for line in wrap(text, width, max_lines))


def build_ass(text: ClipText, duration: float, tpl: Template) -> str:
    ending_start = max(0.0, duration - tpl.ending_seconds)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{tpl.font},{tpl.title_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,8,60,60,110,1
Style: Sub,{tpl.font},{tpl.sub_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,330,1
Style: Ending,{tpl.font},{tpl.ending_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,3,24,0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [
        f"Dialogue: 1,{_ass_time(0)},{_ass_time(ending_start)},Title,,0,0,0,,{_lines(text.title, tpl.title_chars, tpl.title_lines)}",
        f"Dialogue: 2,{_ass_time(ending_start)},{_ass_time(duration)},Ending,,0,0,0,,{_lines(text.ending, tpl.ending_chars, 3)}",
    ]
    for cue in text.subtitles if tpl.burn_subtitles else []:
        end = min(cue.end, ending_start)
        if end > cue.start:
            events.append(
                f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(end)},Sub,,0,0,0,,{_lines(cue.text, tpl.sub_chars, 2)}"
            )
    return header + "\n".join(events) + "\n"


def render_clip(
    source: Path, start: float, duration: float, text: ClipText, out_path: Path, tpl: Template = Template(),  # noqa: B008 - frozen dataclass, safe to share
    limits: RenderLimits = RenderLimits(),  # noqa: B008 - frozen dataclass, safe to share
) -> RenderResult:
    """Cut [start, start+duration) from `source` and render a vertical clip."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path = out_path.with_suffix(".ass")
    ass_path.write_text(build_ass(text, duration, tpl), encoding="utf-8")

    # Blurred fill + fitted foreground keeps the whole source frame visible for any aspect ratio.
    content_h = HEIGHT - tpl.title_band
    graph = (
        f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
        f"boxblur=20:2,eq=brightness=-0.12[bg];"
        f"[0:v]scale={WIDTH}:{content_h}:force_original_aspect_ratio=decrease,setsar=1[fg];"
        f"[bg][fg]overlay=(W-w)/2:{tpl.title_band}+({content_h}-h)/2,fps={FPS},"
        f"subtitles={ass_path.name},format=yuv420p[v]"
    )
    cmd = [
        binary("ffmpeg"), "-y", "-v", "error", *CPU_ARGS,
        "-ss", f"{start:.3f}", "-i", str(source.resolve()), "-t", f"{duration:.3f}",
        "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", *X264_ARGS,
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-threads", str(ENCODER_THREADS), "-filter_complex_threads", str(limits.threads),
        *BITEXACT_ARGS, "-movflags", "+faststart", out_path.name,
    ]
    # Run inside the output folder so the subtitles filter gets a plain relative path
    # (Windows drive-letter colons would otherwise need filtergraph escaping).
    timeout = limits.timeout_for(duration)
    try:
        subprocess.run(cmd, cwd=out_path.parent, check=True, capture_output=True, text=True, encoding="utf-8",
                       timeout=timeout, creationflags=_priority_flags(limits))
    except subprocess.TimeoutExpired as exc:
        out_path.unlink(missing_ok=True)
        raise RenderError(f"{out_path.name}: render took longer than {timeout:.0f}s and was stopped") from exc

    info = probe(out_path)
    problems = duration_gaps(info, duration, DURATION_TOLERANCE_S)
    if problems:
        raise RenderError(f"{out_path.name}: " + "; ".join(problems))
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    return RenderResult(
        path=out_path,
        sha256=hashlib.sha256(out_path.read_bytes()).hexdigest(),
        width=int(video["width"]),
        height=int(video["height"]),
        duration_s=float(info["format"]["duration"]),
        video_codec=video["codec_name"],
        audio_codec=audio["codec_name"] if audio else None,
        template_version=tpl.version,
    )
