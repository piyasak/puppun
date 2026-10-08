"""The P1 media pipeline as reusable steps, shared by the POC CLI and the Agent job runner (P3.3).

    plan()       inspect the source, fetch captions, find audio pauses, pick seeded segments
    fetch_part() download one selected range (linked source) or point into the customer file
    render()     render one 9:16 clip with the fixed Thai text template

Network steps raise SourceError; a render that does not match the request raises RenderError.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from clipflow_worker import segments as seg
from clipflow_worker.local_source import inspect_local, sidecar_captions
from clipflow_worker.netguard import public_only
from clipflow_worker.poc import analyze_pauses, clip_text, detect_pauses, download_range, fetch_captions
from clipflow_worker.render import RenderResult, Template, render_clip
from clipflow_worker.source import DEFAULT_MAX_DURATION_S, SourceInfo, check_limits, inspect


@dataclass
class Plan:
    info: SourceInfo
    url: str | None
    local: Path | None
    work: Path
    cues: list[seg.Cue]
    caption_track: str | None
    pauses: int
    noise_db: int
    selection: seg.Selection


def plan(*, work: Path, count: int, seed: int, min_len: float, max_len: float, url: str | None = None,
         local: Path | None = None, captions: Path | None = None,
         max_duration: int = DEFAULT_MAX_DURATION_S, info: SourceInfo | None = None) -> Plan:
    """Everything needed before any clip is cut. Exactly one of `url` / `local`; `info` if already inspected."""
    if bool(url) == bool(local):
        raise ValueError("plan needs exactly one of url or local")
    # Every network step of a linked source runs under the SSRF guard (T08, E-38).
    with nullcontext() if local else public_only():
        return _plan(work=work, count=count, seed=seed, min_len=min_len, max_len=max_len, url=url, local=local,
                     captions=captions, max_duration=max_duration, info=info)


def _plan(*, work, count, seed, min_len, max_len, url, local, captions, max_duration, info) -> Plan:
    info = info or (inspect_local(local) if local else inspect(url))
    check_limits(info, max_duration)
    work.mkdir(parents=True, exist_ok=True)
    if local:
        captions = captions or sidecar_captions(local)
        pauses, noise_db = analyze_pauses(local, info.duration_s)
    else:
        captions = fetch_captions(url, info, work)
        pauses, noise_db = detect_pauses(url, work, info.duration_s)
    candidates = seg.pause_candidates(pauses, min_len, max_len)
    if not candidates:
        candidates = seg.time_candidates(info.duration_s, min_len, max_len)
    return Plan(info=info, url=url, local=local, work=work, cues=seg.load_cues(captions) if captions else [],
                caption_track=captions.name if captions else None, pauses=len(pauses), noise_db=noise_db,
                selection=seg.select(candidates, count, seed))


def fetch_part(p: Plan, segment: seg.Segment, max_height: int = 1080) -> tuple[Path, float]:
    """(file, offset of the segment inside it). The customer's file is cut directly."""
    if p.local:
        return p.local, segment.start
    with public_only():
        return download_range(p.url, segment.start, segment.end, p.work, max_height), 0.0


def render(p: Plan, index: int, segment: seg.Segment, part: Path, offset: float, out: Path,
           tpl: Template) -> tuple[RenderResult, dict, int]:
    """Returns (render result, text metadata, subtitle cue count)."""
    text, metadata = clip_text(p.info.title, index, len(p.selection.segments))
    text.subtitles = seg.cues_within(p.cues, segment)
    return render_clip(part, offset, segment.duration, text, out, tpl), metadata, len(text.subtitles)
