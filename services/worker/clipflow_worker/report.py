"""Summarize POC manifests into the markdown evidence tables used in docs/compatibility.md.

    python -m clipflow_worker.report var/poc
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def load(root: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*/manifest.json"))]


def render_table(manifests: list[dict]) -> str:
    rows = [
        "| Platform | Source ID | Source length | Captions | Pauses (threshold) | Seed | Clips | Clip lengths (s) | 1080×1920 H.264+AAC | Subtitle cues | Total time (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in manifests:
        src, sel, clips = m["source"], m["selection"], m["clips"]
        ok = all(
            c["render"]["width"] == 1080 and c["render"]["height"] == 1920
            and c["render"]["video_codec"] == "h264" and c["render"]["audio_codec"] == "aac"
            for c in clips
        )
        rows.append(
            f"| {src['platform']} | {src['source_id']} | {src['duration_s'] // 60} min | {sel['caption_track'] or 'none'} "
            f"| {sel.get('audio_pauses')} ({sel.get('silence_threshold_db')} dB) | {sel['seed']} "
            f"| {sel['produced']}/{sel['requested']} | {', '.join(f'{c['render']['duration_s']:.1f}' for c in clips)} "
            f"| {'yes' if ok and clips else 'NO'} | {', '.join(str(c['subtitle_cues']) for c in clips)} "
            f"| {m['timing_s']['total']} |"
        )
    return "\n".join(rows)


def render_benchmark(manifests: list[dict]) -> str:
    clips = [c for m in manifests for c in m["clips"]]
    if not clips:
        return "no clips"
    dl = [c["timing_s"]["download"] for c in clips]
    rd = [c["timing_s"]["render"] for c in clips]
    secs = [c["render"]["duration_s"] for c in clips]
    analysis = [m["timing_s"]["inspect_and_select"] for m in manifests]
    return (
        f"clips={len(clips)}, clip seconds total={sum(secs):.0f}\n"
        f"range download per clip: mean {statistics.mean(dl):.1f}s, max {max(dl):.1f}s\n"
        f"render per clip: mean {statistics.mean(rd):.1f}s, max {max(rd):.1f}s "
        f"(render/clip-second = {sum(rd) / sum(secs):.2f})\n"
        f"inspect + captions + audio analysis per source: mean {statistics.mean(analysis):.1f}s, max {max(analysis):.1f}s"
    )


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = Path((argv or sys.argv[1:] or ["var/poc"])[0])
    manifests = load(root)
    print(render_table(manifests))
    print()
    print(render_benchmark(manifests))
    return 0


if __name__ == "__main__":
    sys.exit(main())
