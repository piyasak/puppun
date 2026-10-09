"""Boundary detection and seeded segment selection (FR-04, FR-05).

Clips start and end inside real audio pauses (ffmpeg silencedetect), so a clip
does not start or stop mid-sentence. Caption cues are not used as boundaries:
YouTube's Thai auto captions are contiguous and split words across cues (P1
finding, 2026-10-07). Captions are only used for the burned-in subtitles.
Selection is random but fully determined by the seed, which is stored with the
clip so the same input reproduces the same intervals.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path

SELECTION_VERSION = "seg-v2-audio-pause"


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    method: str

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {**asdict(self), "duration": round(self.duration, 3)}


@dataclass
class Selection:
    seed: int
    requested: int
    segments: list[Segment]
    candidates: int
    version: str = SELECTION_VERSION

    @property
    def insufficient(self) -> bool:
        return len(self.segments) < self.requested


def parse_json3(text: str) -> list[Cue]:
    """YouTube json3 caption format."""
    cues = []
    for event in json.loads(text).get("events", []):
        segs = event.get("segs")
        if not segs or "tStartMs" not in event:
            continue
        body = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if not body:
            continue
        start = event["tStartMs"] / 1000
        cues.append(Cue(start, start + event.get("dDurationMs", 0) / 1000, body))
    return _normalize(cues)


_SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{3})")


def _srt_seconds(stamp: str) -> float:
    h, m, s, ms = map(int, _SRT_TIME.match(stamp.strip()).groups())
    return h * 3600 + m * 60 + s + ms / 1000


def parse_srt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        timing = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing is None:
            continue
        start, end = (part.strip().split(" ")[0] for part in lines[timing].split("-->"))
        body = " ".join(lines[timing + 1 :]).strip()
        if body:
            cues.append(Cue(_srt_seconds(start), _srt_seconds(end), body))
    return _normalize(cues)


def load_cues(path: Path) -> list[Cue]:
    text = path.read_text(encoding="utf-8")
    return parse_json3(text) if path.suffix == ".json3" else parse_srt(text)


def _normalize(cues: list[Cue]) -> list[Cue]:
    """Sort and clip overlaps (auto captions overlap the next cue while it rolls in)."""
    cues = sorted(cues, key=lambda c: c.start)
    out: list[Cue] = []
    for i, cue in enumerate(cues):
        end = min(cue.end, cues[i + 1].start) if i + 1 < len(cues) else cue.end
        if end > cue.start:
            out.append(Cue(cue.start, end, cue.text))
    return out


def candidate_segments(
    cues: list[Cue], min_len: float, max_len: float, min_pause: float = 0.25
) -> list[Segment]:
    """All windows [cue_i.start, cue_j.end] bounded by pauses and within length limits."""
    if not cues:
        return []
    starts_ok = [i == 0 or cues[i].start - cues[i - 1].end >= min_pause for i in range(len(cues))]
    ends_ok = [i == len(cues) - 1 or cues[i + 1].start - cues[i].end >= min_pause for i in range(len(cues))]
    out = []
    for i, cue in enumerate(cues):
        if not starts_ok[i]:
            continue
        for j in range(i, len(cues)):
            length = cues[j].end - cue.start
            if length > max_len:
                break
            if length >= min_len and ends_ok[j]:
                out.append(Segment(cue.start, cues[j].end, "transcript_boundary"))
    return out


_SILENCE = re.compile(r"silence_(start|end): (-?[\d.]+)")


def parse_silencedetect(stderr: str) -> list[tuple[float, float]]:
    """Pause intervals from ffmpeg `-af silencedetect` log output."""
    pauses, start = [], None
    for kind, value in _SILENCE.findall(stderr):
        if kind == "start":
            start = max(0.0, float(value))
        elif start is not None:
            pauses.append((start, float(value)))
            start = None
    return pauses


def pause_candidates(pauses: list[tuple[float, float]], min_len: float, max_len: float) -> list[Segment]:
    """Windows from one pause midpoint to a later one, within length limits."""
    points = [round((a + b) / 2, 3) for a, b in pauses]
    out = []
    for i, start in enumerate(points):
        for end in points[i + 1 :]:
            length = end - start
            if length > max_len:
                break
            if length >= min_len:
                out.append(Segment(start, end, "audio_pause_boundary"))
    return out


def time_candidates(duration: float, min_len: float, max_len: float, step: float = 5.0) -> list[Segment]:
    """Fallback without a transcript: windows on a fixed grid, skipping the first/last 3%."""
    margin = duration * 0.03
    length = (min_len + max_len) / 2
    out = []
    t = margin
    while t + length <= duration - margin:
        out.append(Segment(round(t, 3), round(t + length, 3), "time_grid_no_transcript"))
        t += step
    return out


LAST_CLIP_STRETCH = 1.2  # the last clip of a whole-source split may run this much over max_len (Q-32)


def tile(pauses: list[tuple[float, float]], duration: float, min_len: float, max_len: float) -> list[Segment]:
    """Split the whole source into consecutive clips (Q-32: the clip count follows the source).

    Balanced first: the fewest clips that keep every clip <= max_len, cut near equal lengths at the
    nearest pause midpoint (a time cut where none fits) while keeping the rest splittable. When equal
    clips would be shorter than min_len, clips are cut at max_len instead and the last may stretch to
    LAST_CLIP_STRETCH x max_len; a tail too short to be a clip that cannot join the last one is left
    out, never padded or made into a too-short clip (T09).
    """
    mids = sorted(round((a + b) / 2, 3) for a, b in pauses)
    n = math.ceil(duration / max_len) if duration > 0 else 0
    if n and duration / n >= min_len:
        return _tile_balanced(mids, duration, n, min_len, max_len)
    return _tile_greedy(mids, duration, min_len, max_len)


def _tile_balanced(mids, duration, n, min_len, max_len) -> list[Segment]:
    out: list[Segment] = []
    start = 0.0
    for i in range(n - 1):
        left = n - i  # clips still to make, this one included
        target = start + (duration - start) / left
        lo = max(start + min_len, duration - (left - 1) * max_len)
        hi = min(start + max_len, duration - (left - 1) * min_len)
        fits = [m for m in mids if lo <= m <= hi]
        if fits:
            end, method = min(fits, key=lambda m: abs(m - target)), "tile_audio_pause"
        else:
            end, method = round(min(max(target, lo), hi), 3), "tile_time"
        out.append(Segment(round(start, 3), end, method))
        start = end
    out.append(Segment(round(start, 3), round(duration, 3), "tile_end"))
    return out


def _tile_greedy(mids, duration, min_len, max_len) -> list[Segment]:
    longest_last = max_len * LAST_CLIP_STRETCH
    out: list[Segment] = []
    start = 0.0
    while duration - start > longest_last:
        fits = [m for m in mids if start + min_len <= m <= start + max_len]
        end, method = (fits[-1], "tile_audio_pause") if fits else (round(start + max_len, 3), "tile_time")
        out.append(Segment(round(start, 3), end, method))
        start = end
    rest = duration - start
    if rest >= min_len:
        out.append(Segment(round(start, 3), round(duration, 3), "tile_end"))
    elif out and out[-1].duration + rest <= longest_last:
        out[-1] = Segment(out[-1].start, round(duration, 3), out[-1].method)
    return out


def select(candidates: list[Segment], count: int, seed: int) -> Selection:
    """Pick up to `count` non-overlapping candidates in a seed-determined order."""
    rng = random.Random(seed)
    order = list(candidates)
    rng.shuffle(order)
    chosen: list[Segment] = []
    for seg in order:
        if len(chosen) == count:
            break
        if all(seg.end <= c.start or seg.start >= c.end for c in chosen):
            chosen.append(seg)
    return Selection(seed=seed, requested=count, segments=sorted(chosen, key=lambda s: s.start), candidates=len(candidates))


def cues_within(cues: list[Cue], seg: Segment) -> list[Cue]:
    """Cues inside a segment, re-timed relative to the segment start."""
    return [
        Cue(round(max(c.start, seg.start) - seg.start, 3), round(min(c.end, seg.end) - seg.start, 3), c.text)
        for c in cues
        if c.end > seg.start and c.start < seg.end
    ]
