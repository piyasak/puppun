"""TEMPORARY diagnostic (removed before merge): which part of the new render differs by CPU."""
import subprocess, sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
src = out / "src.mkv"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=30",
                "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*sin(2*PI*0.3*t)':s=44100:d=30",
                "-c:v", "ffv1", "-c:a", "flac", str(src)], check=True)
code = r"""
import sys, subprocess; sys.path.insert(0, sys.argv[1])
from pathlib import Path
import clipflow_worker.render as R
from clipflow_worker.segments import Cue
variant = sys.argv[4]; real = subprocess.run
def run(cmd, **kw):
    if "libx264" in cmd:
        cmd = list(cmd)
        if variant.startswith("cpuind_only"):
            i = cmd.index("-x264-params") + 1; cmd[i] = "cpu-independent=1"
        if variant == "nosubs":
            i = cmd.index("-filter_complex") + 1; cmd[i] = cmd[i].replace("subtitles=clip.ass,", "")
        if variant == "x264_c":
            i = cmd.index("-x264-params") + 1; cmd[i] = "asm=0"
        if variant == "lav_c":
            cmd[cmd.index("-cpuflags") + 1] = "0"
        if variant == "x264_c_nosubs":
            i = cmd.index("-filter_complex") + 1; cmd[i] = cmd[i].replace("subtitles=clip.ass,", "")
            i = cmd.index("-x264-params") + 1; cmd[i] = "asm=0"
    return real(cmd, **kw)
R.subprocess.run = run
t = R.ClipText("ทดสอบ ตอนที่ 1/2", "ติดตามตอนต่อไป", [Cue(1.0, 4.0, "สวัสดีครับ")])
r = R.render_clip(Path(sys.argv[2]), 3.0, 20.0, t, Path(sys.argv[3]), limits=R.RenderLimits(threads=2))
print(r.sha256)
"""
def md5(f, sel):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-map", sel, "-c", "copy", "-f", "md5", "-"],
                          capture_output=True, text=True).stdout.strip()[-8:]
for variant in ("new", "new", "new", "cpuind_only", "cpuind_only", "cpuind_only", "x264_c"):
    f = out / f"{variant}_{len(list(out.glob(variant + '*')))}" / "clip.mp4"
    subprocess.run([sys.executable, "-c", code, str(repo / "services/worker"), str(src), str(f), variant],
                   capture_output=True, text=True, check=True)
    print(f"RESULT {variant} v={md5(f, '0:v')} a={md5(f, '0:a')}", flush=True)
