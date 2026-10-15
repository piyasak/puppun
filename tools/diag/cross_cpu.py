"""TEMPORARY diagnostic (removed before merge): same segment, old vs new render args, on this CPU."""
import hashlib, shutil, subprocess, sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
old_pkg = out / "old"; shutil.copytree(repo / "services/worker/clipflow_worker", old_pkg / "clipflow_worker", dirs_exist_ok=True)
(old_pkg / "clipflow_worker/render.py").write_bytes(subprocess.run(
    ["git", "show", "origin/master:services/worker/clipflow_worker/render.py"], cwd=repo, capture_output=True, check=True).stdout)
src = out / "src.mkv"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=30",
                "-f", "lavfi", "-i", "aevalsrc='0.5*sin(2*PI*440*t)*sin(2*PI*0.3*t)':s=44100:d=30",
                "-c:v", "ffv1", "-c:a", "flac", str(src)], check=True)
code = """
import sys; sys.path.insert(0, sys.argv[1])
from pathlib import Path
from clipflow_worker.render import render_clip, ClipText, RenderLimits
from clipflow_worker.segments import Cue
t = ClipText("ทดสอบ ตอนที่ 1/2", "ติดตามตอนต่อไป", [Cue(1.0, 4.0, "สวัสดีครับ")])
r = render_clip(Path(sys.argv[2]), 3.0, 20.0, t, Path(sys.argv[3]), limits=RenderLimits(threads=int(sys.argv[4])))
print(r.sha256)
"""
def md5(f, sel):
    return subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-map", sel, "-c", "copy", "-f", "md5", "-"],
                          capture_output=True, text=True).stdout.strip()[-8:]
for name, pkg in (("old", old_pkg), ("new", repo / "services/worker")):
    for threads in (1, 2):
        f = out / f"{name}_{threads}" / "clip.mp4"
        sha = subprocess.run([sys.executable, "-c", code, str(pkg), str(src), str(f), str(threads)],
                             capture_output=True, text=True, check=True).stdout.strip()
        print(f"RESULT {name} threads={threads} sha={sha[:12]} v={md5(f, '0:v')} a={md5(f, '0:a')}", flush=True)
