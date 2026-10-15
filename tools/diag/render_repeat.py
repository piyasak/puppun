"""TEMPORARY diagnostic (removed before merge): render one segment many times, compare hashes."""
import hashlib, os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "worker"))
from clipflow_worker.render import ClipText, Template, build_ass, WIDTH, HEIGHT, FPS  # noqa: E402
from clipflow_worker.segments import Cue  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
n = int(sys.argv[2])
only = sys.argv[3].split(",") if len(sys.argv) > 3 else None
src = out / "source.mp4"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=70",
                "-f", "lavfi", "-i", "aevalsrc='if(lt(mod(t,10),9),0.5*sin(2*PI*440*t),0)':s=44100:d=70",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(src)], check=True)
tpl = Template()
(out / "c.ass").write_text(build_ass(ClipText("ทดสอบ ตอนที่ 1/2", "ติดตามตอนต่อไป", [Cue(1, 4, "สวัสดี")]), 19.0, tpl), encoding="utf-8")
ch = HEIGHT - tpl.title_band
graph = (f"[0:v]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},boxblur=20:2,eq=brightness=-0.12[bg];"
         f"[0:v]scale={WIDTH}:{ch}:force_original_aspect_ratio=decrease,setsar=1[fg];"
         f"[bg][fg]overlay=(W-w)/2:{tpl.title_band}+({ch}-h)/2,fps={FPS},subtitles=c.ass,format=yuv420p[v]")
t = str(max(1, (os.cpu_count() or 2) // 2))
base = ["-filter_complex", graph, "-map", "[v]", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
variants = {
    "old": base + ["-threads", t, "-filter_complex_threads", t, "-movflags", "+faststart"],
    "bitexact": base + ["-threads", t, "-filter_complex_threads", t, "-map_metadata", "-1", "-fflags", "+bitexact",
                        "-flags:v", "+bitexact", "-flags:a", "+bitexact", "-movflags", "+faststart"],
    "threads1_filters": base + ["-threads", t, "-filter_complex_threads", "1", "-movflags", "+faststart"],
    "x264_1": base + ["-threads", "1", "-filter_complex_threads", t, "-movflags", "+faststart"],
    "nofaststart": base + ["-threads", t, "-filter_complex_threads", t],
}
print("cpu_count", os.cpu_count(), "threads", t, flush=True)


def stream_md5(path, sel):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", sel, "-c", "copy", "-f", "md5", "-"],
                       capture_output=True, text=True)
    return r.stdout.strip()[-8:]


for name, args in variants.items():
    if only and name not in only:
        continue
    seen = {}
    for i in range(n):
        f = out / f"{name}_{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "9.500", "-i", str(src), "-t", "19.000", *args, f.name],
                       cwd=out, check=True)
        key = (hashlib.sha256(f.read_bytes()).hexdigest()[:10], stream_md5(f, "0:v"), stream_md5(f, "0:a"),
               f.stat().st_size)
        seen[key] = seen.get(key, 0) + 1
        f.unlink()
    print(name, "distinct", len(seen), seen, flush=True)
