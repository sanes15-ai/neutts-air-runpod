"""ffmpeg/ffprobe discovery and helpers."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CACHE_DIRS = [
    Path.home() / ".promptcut" / "ffmpeg",
    Path(__file__).resolve().parents[2] / ".ffmpeg",
]


class FFmpegNotFound(RuntimeError):
    pass


def _candidates(name):
    sys_bin = shutil.which(name)
    if sys_bin:
        yield Path(sys_bin)
    for d in CACHE_DIRS:
        p = d / name
        if p.exists():
            yield p
        for sub in sorted(d.glob("ffmpeg-*-static")) if d.exists() else []:
            q = sub / name
            if q.exists():
                yield q


def find(name="ffmpeg"):
    for p in _candidates(name):
        try:
            subprocess.run([str(p), "-version"], capture_output=True, check=True)
            return str(p)
        except Exception:
            continue
    raise FFmpegNotFound(
        f"{name} not found. Run scripts/get_ffmpeg.sh (downloads a static build "
        f"into ~/.promptcut/ffmpeg) or install {name} on your PATH."
    )


def run(args, quiet=True, ffmpeg_bin=None):
    """Run ffmpeg with sane defaults; raises with stderr tail on failure."""
    bin_ = ffmpeg_bin or find("ffmpeg")
    cmd = [bin_, "-hide_banner", "-y"] + (["-v", "error"] if quiet else []) + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}):\n{tail}\ncmd: {' '.join(cmd)}")
    return proc


def probe(path):
    """Return {'duration','width','height','fps','has_audio','has_video','sample_rate'}."""
    bin_ = find("ffprobe")
    proc = subprocess.run(
        [bin_, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {proc.stderr.strip()[-400:]}")
    data = json.loads(proc.stdout)
    out = {"duration": float(data.get("format", {}).get("duration", 0) or 0),
           "width": None, "height": None, "fps": None,
           "has_video": False, "has_audio": False, "sample_rate": None}
    for s in data.get("streams", []):
        if s["codec_type"] == "video" and not out["has_video"]:
            out["has_video"] = True
            out["width"], out["height"] = s.get("width"), s.get("height")
            num, _, den = (s.get("avg_frame_rate") or "0/1").partition("/")
            try:
                out["fps"] = round(float(num) / float(den or 1), 3) if float(den or 1) else None
            except ValueError:
                out["fps"] = None
            if not out["duration"] and s.get("duration"):
                out["duration"] = float(s["duration"])
        elif s["codec_type"] == "audio" and not out["has_audio"]:
            out["has_audio"] = True
            out["sample_rate"] = int(s.get("sample_rate") or 0)
    return out


def find_font():
    """Locate a usable TTF for drawtext/ASS fallback."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]
    env = os.environ.get("PROMPTCUT_FONT")
    if env and Path(env).exists():
        return env
    for c in candidates:
        if Path(c).exists():
            return c
    return None
