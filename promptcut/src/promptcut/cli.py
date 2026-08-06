"""PromptCut CLI — the agent-facing surface of the editor."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__, captions as cap
from . import compiler, ffmpeg as ff, looks, project as prj


def _root(args):
    return Path(getattr(args, "project", ".") or ".").resolve()


def _load(args):
    return prj.load(_root(args))


def _say(obj):
    print(json.dumps(obj, indent=2) if not isinstance(obj, str) else obj)


# ----------------------------------------------------------------- commands

def cmd_new(args):
    root = _root(args)
    w, h = (int(x) for x in args.size.split("x"))
    proj = prj.new_project(args.name, w, h, args.fps)
    (root / "media").mkdir(parents=True, exist_ok=True)
    path = prj.save(proj, root)
    _say(f"created {path} ({w}x{h} @ {args.fps}fps). Add media: promptcut add <files>")


def cmd_add(args):
    root = _root(args)
    proj = _load(args)
    media = root / "media"
    media.mkdir(exist_ok=True)
    added = {}
    for f in args.files:
        src = Path(f).expanduser().resolve()
        if not src.exists():
            sys.exit(f"not found: {src}")
        dest = media / src.name
        if src != dest and not dest.exists():
            if args.link:
                dest.symlink_to(src)
            else:
                shutil.copy2(src, dest)
        aid = args.id or src.stem.lower().replace(" ", "_")[:24]
        base_aid, n = aid, 2
        while aid in proj["assets"]:
            aid = f"{base_aid}{n}"; n += 1
        proj["assets"][aid] = {"path": f"media/{dest.name}"}
        info = ff.probe(dest)
        added[aid] = {"path": f"media/{dest.name}", **info}
    prj.save(proj, root)
    _say(added)


def cmd_probe(args):
    root = _root(args)
    target = Path(args.target)
    if not target.exists():
        proj = _load(args)
        if args.target in proj["assets"]:
            target = root / proj["assets"][args.target]["path"]
        else:
            sys.exit(f"no such file or asset id: {args.target}")
    _say(ff.probe(target))


def cmd_status(args):
    proj = _load(args)
    starts = prj.clip_start_times(proj)
    clips = [{"id": c["id"], "asset": c["asset"], "start": round(s, 3),
              "duration": round(prj.clip_duration(c), 3),
              "in": c["in"], "out": c["out"],
              "speed": c.get("speed", 1.0), "ramp": bool(c.get("ramp")),
              "transition_out": (c.get("transition_out") or {}).get("type"),
              "look": (c.get("color") or {}).get("look")}
             for c, s in zip(proj["timeline"]["video"], starts)]
    _say({"name": proj["name"], "settings": proj["settings"],
          "duration": round(prj.timeline_duration(proj), 3),
          "clips": clips,
          "overlays": len(proj["timeline"]["overlays"]),
          "texts": len(proj["timeline"]["texts"]),
          "captions": len(proj["timeline"]["captions"].get("segments", [])),
          "music": len(proj["timeline"]["music"])})


def cmd_silences(args):
    root = _root(args)
    proj = _load(args)
    src = root / proj["assets"][args.asset]["path"]
    _say({"silences": cap.detect_silences(src, args.noise, args.min_silence),
          "speech": cap.speech_spans(src, args.noise, args.min_silence, args.margin)})


def cmd_autocut(args):
    """Rebuild the main track from an asset, cutting silences."""
    root = _root(args)
    proj = _load(args)
    src = root / proj["assets"][args.asset]["path"]
    spans = cap.speech_spans(src, args.noise, args.min_silence, args.margin)
    if not spans:
        sys.exit("no speech spans detected — try a higher --noise (e.g. -40)")
    proj["timeline"]["video"] = [
        {"id": f"cut{i + 1}", "asset": args.asset,
         "in": s["start"], "out": s["end"]}
        for i, s in enumerate(spans)]
    prj.save(proj, root)
    _say({"clips": len(spans),
          "duration": round(prj.timeline_duration(proj), 3),
          "note": "main track rebuilt; render a preview to check the cut"})


def cmd_captions(args):
    root = _root(args)
    proj = _load(args)
    if args.srt:
        segs = cap.parse_srt(args.srt)
    elif args.transcribe:
        src = root / proj["assets"][args.transcribe]["path"]
        segs = cap.transcribe(src, args.model, args.language)
    else:
        sys.exit("pass --srt <file> or --transcribe <asset-id>")
    proj["timeline"]["captions"] = {"style": args.style, "segments": segs}
    prj.save(proj, root)
    _say({"segments": len(segs), "style": args.style})


def cmd_render(args):
    root = _root(args)
    proj = _load(args)
    mode = "preview" if args.preview else "final"
    out = compiler.render(proj, root, mode=mode, out_path=args.out)
    info = ff.probe(out)
    _say({"output": str(out), "duration": round(info["duration"], 2),
          "size_mb": round(Path(out).stat().st_size / 1e6, 2),
          "resolution": f"{info['width']}x{info['height']}"})


def cmd_frames(args):
    root = _root(args)
    proj = _load(args)
    mode = "preview" if not args.final else "final"
    suffix = "_preview" if mode == "preview" else ""
    video = root / "render" / f"{proj['name']}{suffix}.mp4"
    if not video.exists():
        video = compiler.render(proj, root, mode=mode)
    if args.times:
        times = [float(t) for t in args.times.split(",")]
    else:
        dur = ff.probe(video)["duration"]
        n = args.count
        times = [dur * (i + 0.5) / n for i in range(n)]
    paths = compiler.export_frames(video, times, root / ".cache" / "frames",
                                   width=args.width)
    _say([str(p) for p in paths])


def cmd_looks(args):
    _say({"looks": sorted(looks.LOOKS),
          "transitions": sorted(prj.TRANSITIONS),
          "caption_styles": list(cap.STYLES)})


def cmd_doctor(args):
    out = {"promptcut": __version__}
    try:
        import subprocess
        v = subprocess.run([ff.find("ffmpeg"), "-version"],
                           capture_output=True, text=True).stdout.splitlines()[0]
        out["ffmpeg"] = v
    except Exception as e:
        out["ffmpeg"] = f"MISSING — {e}"
    try:
        ff.find("ffprobe"); out["ffprobe"] = "ok"
    except Exception as e:
        out["ffprobe"] = f"MISSING — {e}"
    out["font"] = ff.find_font() or "none found (set PROMPTCUT_FONT=/path/to/font.ttf)"
    try:
        import faster_whisper  # noqa: F401
        out["transcribe"] = "faster-whisper available"
    except ImportError:
        out["transcribe"] = "not installed (optional): pip install 'promptcut[transcribe]'"
    _say(out)


def cmd_serve(args):
    from . import server
    server.serve(_root(args), host=args.host, port=args.port)


# ----------------------------------------------------------------- parser

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="promptcut",
        description="Prompt-driven video editor: edit project.json, render with ffmpeg.")
    p.add_argument("--project", "-p", default=".", help="project directory (default: cwd)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="create a project here")
    s.add_argument("name")
    s.add_argument("--size", default="1920x1080")
    s.add_argument("--fps", type=int, default=30)
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("add", help="import media files as assets")
    s.add_argument("files", nargs="+")
    s.add_argument("--id", help="asset id (default: filename)")
    s.add_argument("--link", action="store_true", help="symlink instead of copy")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("probe", help="media info for an asset id or file")
    s.add_argument("target")
    s.set_defaults(fn=cmd_probe)

    s = sub.add_parser("status", help="timeline summary (durations, clips)")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("silences", help="detect silences/speech spans in an asset")
    s.add_argument("asset")
    s.add_argument("--noise", type=float, default=-32)
    s.add_argument("--min-silence", type=float, default=0.45)
    s.add_argument("--margin", type=float, default=0.12)
    s.set_defaults(fn=cmd_silences)

    s = sub.add_parser("autocut", help="rebuild main track from an asset minus silences")
    s.add_argument("asset")
    s.add_argument("--noise", type=float, default=-32)
    s.add_argument("--min-silence", type=float, default=0.45)
    s.add_argument("--margin", type=float, default=0.12)
    s.set_defaults(fn=cmd_autocut)

    s = sub.add_parser("captions", help="set captions from SRT or Whisper")
    s.add_argument("--srt")
    s.add_argument("--transcribe", metavar="ASSET_ID")
    s.add_argument("--style", default="clean", choices=list(cap.STYLES))
    s.add_argument("--model", default="small")
    s.add_argument("--language", default=None)
    s.set_defaults(fn=cmd_captions)

    s = sub.add_parser("render", help="render the timeline")
    s.add_argument("--preview", action="store_true", help="fast half-res proxy")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("frames", help="export stills from the render to look at")
    s.add_argument("--times", help="comma-separated seconds, e.g. 1.5,3,7")
    s.add_argument("--count", type=int, default=6, help="evenly spaced (default 6)")
    s.add_argument("--width", type=int, default=640)
    s.add_argument("--final", action="store_true", help="use final render, not preview")
    s.set_defaults(fn=cmd_frames)

    s = sub.add_parser("looks", help="list looks, transitions, caption styles")
    s.set_defaults(fn=cmd_looks)

    s = sub.add_parser("doctor", help="check ffmpeg/fonts/optional deps")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("serve", help="self-hosted browser UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=7859)
    s.set_defaults(fn=cmd_serve)

    args = p.parse_args(argv)
    try:
        args.fn(args)
    except (prj.ProjectError, RuntimeError, ValueError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
