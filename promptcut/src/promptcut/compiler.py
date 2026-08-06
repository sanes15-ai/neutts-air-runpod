"""Compile a project timeline to ffmpeg render passes.

Strategy (robust two-pass):
  Pass 1  — every main-track clip is rendered to a normalized intermediate
            (exact WxH/fps/pix_fmt + stereo audio) with its trim, speed/ramp,
            transform (pan/zoom keyframes), color grade and fades baked in.
            Intermediates are content-hashed and cached, so re-renders after
            small timeline edits only redo what changed.
  Pass 2  — intermediates are joined (hard cuts via concat, transitions via
            xfade/acrossfade), then overlays (PiP/chromakey), text layers,
            captions (ASS) and the music/ducking mix are applied, and the
            result is encoded with the chosen export preset.
"""

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

from . import ffmpeg as ff
from . import looks
from .project import (TRANSITIONS, clip_duration, clip_source_span,
                      clip_start_times, merged_audio, merged_color,
                      timeline_duration)

PREVIEW_SCALE = 0.5  # preview renders at half project resolution


# --------------------------------------------------------------------------
# expression helpers
# --------------------------------------------------------------------------

def lerp_expr(keyframes, key, default):
    """Piecewise-linear ffmpeg expression in t for a keyframed value."""
    kfs = [(float(k["t"]), float(k.get(key, default))) for k in keyframes
           if key in k or default is not None]
    kfs = [(t, v) for t, v in kfs]
    if not kfs:
        return None
    kfs.sort()
    if len(kfs) == 1 or all(abs(v - kfs[0][1]) < 1e-9 for _, v in kfs):
        return f"{kfs[0][1]:.6f}"
    expr = f"{kfs[-1][1]:.6f}"  # after the last keyframe: hold
    for (t0, v0), (t1, v1) in reversed(list(zip(kfs, kfs[1:]))):
        seg = f"({v0:.6f}+({v1:.6f}-{v0:.6f})*(t-{t0:.6f})/({t1 - t0:.6f}))"
        expr = f"if(lt(t,{t1:.6f}),{seg},{expr})"
    return f"if(lt(t,{kfs[0][0]:.6f}),{kfs[0][1]:.6f},{expr})"


def esc_drawtext(text):
    return (text.replace("\\", "\\\\").replace(":", "\\:")
                .replace("'", "’").replace("%", "\\%"))


# --------------------------------------------------------------------------
# pass 1 — clip intermediates
# --------------------------------------------------------------------------

def _atempo_chain(speed):
    """Chain atempo stages so each stays within [0.5, 2.0]."""
    stages, s = [], float(speed)
    while s > 2.0:
        stages.append("atempo=2.0"); s /= 2.0
    while s < 0.5:
        stages.append("atempo=0.5"); s /= 0.5
    stages.append(f"atempo={s:.6f}")
    return stages


def _transform_filters(clip, W, H):
    """Pan/zoom keyframes -> scale-to-cover + animated crop + scale."""
    tf = clip.get("transform") or {}
    kfs = tf.get("keyframes") or []
    fit = clip.get("fit", "cover")
    base = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}" if fit == "cover" else
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2")
    if not kfs:
        return [base]
    zoom = lerp_expr(kfs, "zoom", 1.0) or "1"
    px = lerp_expr(kfs, "x", 0.5) or "0.5"
    py = lerp_expr(kfs, "y", 0.5) or "0.5"
    up_w, up_h = W * 2, H * 2  # supersample for smooth sub-pixel pan/zoom
    cw = f"ceil((iw/({zoom}))/2)*2"
    ch = f"ceil((ih/({zoom}))/2)*2"
    cx = f"(iw-iw/({zoom}))*({px})"
    cy = f"(ih-ih/({zoom}))*({py})"
    return [
        f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase,crop={up_w}:{up_h}",
        f"crop=w='{cw}':h='{ch}':x='{cx}':y='{cy}'",
        f"scale={W}:{H}",
    ]


def _clip_hash(clip, asset_path, settings, mode):
    payload = json.dumps({"clip": clip, "asset": str(asset_path),
                          "mtime": os.path.getmtime(asset_path),
                          "settings": settings, "mode": mode}, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def render_clip_intermediate(proj, clip, root, mode="final"):
    """Render one main-track clip to a normalized cached intermediate."""
    st = proj["settings"]
    scale = PREVIEW_SCALE if mode == "preview" else 1.0
    W = int(st["width"] * scale) // 2 * 2
    H = int(st["height"] * scale) // 2 * 2
    fps, sr = st["fps"], st["sample_rate"]

    asset = proj["assets"][clip["asset"]]
    src = Path(root) / asset["path"]
    cache = Path(root) / ".cache" / "clips"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{_clip_hash(clip, src, st, mode)}.mp4"
    if out.exists():
        return out

    info = ff.probe(src)
    has_audio = info["has_audio"]
    cin, cout = float(clip["in"]), float(clip["out"])
    duration = clip_duration(clip)

    vparts, aparts = [], []
    ramp = clip.get("ramp")
    inputs = ["-ss", f"{max(cin - 0.5, 0):.3f}", "-i", str(src)]
    off = max(cin - 0.5, 0)  # input seek offset; filters use src-relative times minus this

    def seg_filters(idx, s_from, s_to, speed):
        s0, s1 = cin - off + s_from, cin - off + s_to
        v = (f"[0:v]trim=start={s0:.4f}:end={s1:.4f},setpts=(PTS-STARTPTS)/{speed:.6f},"
             f"fps={fps}[sv{idx}]")
        if has_audio:
            at = ",".join(_atempo_chain(speed))
            a = (f"[0:a]atrim=start={s0:.4f}:end={s1:.4f},asetpts=PTS-STARTPTS,"
                 f"{at}[sa{idx}]")
        else:
            seg_dur = (s_to - s_from) / speed
            a = (f"anullsrc=channel_layout=stereo:sample_rate={sr},"
                 f"atrim=duration={seg_dur:.4f}[sa{idx}]")
        return v, a

    graph = []
    if ramp:
        n = len(ramp)
        for i, seg in enumerate(ramp):
            v, a = seg_filters(i, float(seg["from"]), float(seg["to"]), float(seg["speed"]))
            graph += [v, a]
        joins = "".join(f"[sv{i}][sa{i}]" for i in range(n))
        graph.append(f"{joins}concat=n={n}:v=1:a=1[rv][ra]")
        vlabel, alabel = "rv", "ra"
    else:
        speed = float(clip.get("speed", 1.0) or 1.0)
        v, a = seg_filters(0, 0.0, cout - cin, speed)
        graph += [v, a]
        vlabel, alabel = "sv0", "sa0"

    # video chain: flip/rotate -> transform -> color -> fades -> normalize
    chain = []
    if clip.get("flip") == "h":
        chain.append("hflip")
    elif clip.get("flip") == "v":
        chain.append("vflip")
    rot = float(clip.get("rotate") or 0)
    if rot:
        chain.append(f"rotate={rot}*PI/180:c=black")
    chain += _transform_filters(clip, W, H)
    chain += looks.color_filters(merged_color(clip), root)
    fi, fo = float(clip.get("fade_in") or 0), float(clip.get("fade_out") or 0)
    if fi:
        chain.append(f"fade=t=in:st=0:d={fi:.3f}")
    if fo:
        chain.append(f"fade=t=out:st={max(duration - fo, 0):.3f}:d={fo:.3f}")
    chain.append("format=yuv420p")
    graph.append(f"[{vlabel}]{','.join(chain)}[vout]")

    # audio chain
    aud = merged_audio(clip)
    achain = [f"aresample={sr}", "pan=stereo|c0=c0|c1=c1" if has_audio else "anull"]
    vol = 0.0 if aud["mute"] else float(aud["volume"])
    if vol != 1.0:
        achain.append(f"volume={vol:.4f}")
    if float(aud["fade_in"]):
        achain.append(f"afade=t=in:st=0:d={float(aud['fade_in']):.3f}")
    if float(aud["fade_out"]):
        achain.append(f"afade=t=out:st={max(duration - float(aud['fade_out']), 0):.3f}"
                      f":d={float(aud['fade_out']):.3f}")
    graph.append(f"[{alabel}]{','.join(achain)}[aout]")

    crf = "28" if mode == "preview" else "17"
    preset = "veryfast" if mode == "preview" else "medium"
    args = inputs + [
        "-filter_complex", ";".join(graph),
        "-map", "[vout]", "-map", "[aout]",
        "-t", f"{duration:.4f}",
        "-c:v", "libx264", "-crf", crf, "-preset", preset,
        "-c:a", "aac", "-b:a", "192k", "-ar", str(sr),
        "-movflags", "+faststart", str(out),
    ]
    ff.run(args)
    return out


# --------------------------------------------------------------------------
# pass 2 — assembly
# --------------------------------------------------------------------------

def render(proj, root, mode="final", out_path=None, quiet=True):
    """Full render. Returns the output path."""
    st = proj["settings"]
    scale = PREVIEW_SCALE if mode == "preview" else 1.0
    W = int(st["width"] * scale) // 2 * 2
    H = int(st["height"] * scale) // 2 * 2
    fps, sr = st["fps"], st["sample_rate"]
    clips = proj["timeline"]["video"]
    if not clips:
        raise ValueError("timeline.video is empty — add at least one clip")

    inters = [render_clip_intermediate(proj, c, root, mode) for c in clips]
    durs = [clip_duration(c) for c in clips]
    total = timeline_duration(proj)

    rend_dir = Path(root) / "render"
    rend_dir.mkdir(exist_ok=True)
    suffix = "_preview" if mode == "preview" else ""
    out = Path(out_path) if out_path else rend_dir / f"{proj['name']}{suffix}.mp4"

    inputs, graph = [], []
    for p in inters:
        inputs += ["-i", str(p)]
    n_main = len(inters)

    # fold main track: xfade for transitions, concat for hard cuts
    if n_main == 1:
        graph.append(f"[0:v]null[mv];[0:a]anull[ma]")
        acc_dur = durs[0]
    else:
        cur_v, cur_a, acc_dur = "0:v", "0:a", durs[0]
        for i in range(1, n_main):
            tr = clips[i - 1].get("transition_out")
            nv, na = f"jv{i}", f"ja{i}"
            if tr and float(tr.get("duration", 0)) > 0:
                td = min(float(tr.get("duration", 0.5)), acc_dur - 0.01, durs[i] - 0.01)
                td = max(td, 0.05)
                kind = TRANSITIONS[tr["type"]]
                off = acc_dur - td
                graph.append(f"[{cur_v}][{i}:v]xfade=transition={kind}"
                             f":duration={td:.3f}:offset={off:.4f}[{nv}]")
                graph.append(f"[{cur_a}][{i}:a]acrossfade=d={td:.3f}[{na}]")
                acc_dur = off + durs[i]
            else:
                graph.append(f"[{cur_v}][{i}:v]concat=n=2:v=1:a=0[{nv}]")
                graph.append(f"[{cur_a}][{i}:a]concat=n=2:v=0:a=1[{na}]")
                acc_dur += durs[i]
            cur_v, cur_a = nv, na
        graph.append(f"[{cur_v}]null[mv];[{cur_a}]anull[ma]")

    # overlays (PiP)
    vlabel = "mv"
    idx_in = n_main
    for k, ov in enumerate(proj["timeline"]["overlays"]):
        asset = proj["assets"][ov["asset"]]
        src = Path(root) / asset["path"]
        oin = float(ov.get("in", 0)); oout = ov.get("out")
        inputs += ["-i", str(src)]
        olabel = f"ov{k}"
        start = float(ov.get("start", 0))
        oscale = float(ov.get("scale", 0.3))
        ow = int(W * oscale) // 2 * 2
        chain = [f"trim=start={oin:.3f}" + (f":end={float(oout):.3f}" if oout is not None else ""),
                 "setpts=PTS-STARTPTS", f"fps={fps}", f"scale={ow}:-2"]
        ck = ov.get("chromakey")
        if ck:
            chain.append("format=yuva420p")
            chain.append(f"chromakey=color={ck.get('color', '0x00d000')}"
                         f":similarity={float(ck.get('similarity', 0.18)):.3f}"
                         f":blend={float(ck.get('blend', 0.08)):.3f}")
        else:
            chain.append("format=yuva420p")
        op = float(ov.get("opacity", 1.0))
        if op < 1.0:
            chain.append(f"colorchannelmixer=aa={op:.3f}")
        fi = float(ov.get("fade_in") or 0); fo = float(ov.get("fade_out") or 0)
        odur = (float(oout) - oin) if oout is not None else None
        if fi:
            chain.append(f"fade=t=in:st=0:d={fi:.3f}:alpha=1")
        if fo and odur:
            chain.append(f"fade=t=out:st={max(odur - fo, 0):.3f}:d={fo:.3f}:alpha=1")
        chain.append(f"setpts=PTS+{start:.4f}/TB")
        graph.append(f"[{idx_in}:v]{','.join(chain)}[{olabel}]")
        x = float(ov.get("x", 0.7)); y = float(ov.get("y", 0.1))
        end = start + (odur if odur is not None else 10 ** 6)
        nv = f"mvo{k}"
        graph.append(f"[{vlabel}][{olabel}]overlay=x={x:.4f}*(W-w):y={y:.4f}*(H-h)"
                     f":enable='between(t,{start:.3f},{end:.3f})'[{nv}]")
        vlabel = nv
        idx_in += 1

    # text layers + captions — one ASS pass (libass renders both)
    caps = proj["timeline"].get("captions") or {}
    if caps.get("segments") or proj["timeline"]["texts"]:
        from . import captions as cap_mod
        ass_rel = cap_mod.build_ass(proj, root, scale=scale)
        nv = "mvcap"
        graph.append(f"[{vlabel}]subtitles=filename={ass_rel}[{nv}]")
        vlabel = nv

    # music / extra audio
    alabel = "ma"
    music = proj["timeline"]["music"]
    mix_labels = []
    for k, m in enumerate(music):
        asset = proj["assets"][m["asset"]]
        src = Path(root) / asset["path"]
        if m.get("loop"):
            inputs += ["-stream_loop", "-1", "-i", str(src)]
        else:
            inputs += ["-i", str(src)]
        lab = f"mus{k}"
        min_ = float(m.get("in", 0) or 0)
        mout = m.get("out")
        start = float(m.get("start", 0) or 0)
        end_limit = mout if mout is not None else total - start + min_
        chain = [f"atrim=start={min_:.3f}:end={float(end_limit):.3f}",
                 "asetpts=PTS-STARTPTS", f"aresample={sr}"]
        vol = float(m.get("volume", 1.0))
        if vol != 1.0:
            chain.append(f"volume={vol:.4f}")
        fi = float(m.get("fade_in") or 0); fo = float(m.get("fade_out") or 0)
        mdur = float(end_limit) - min_
        if fi:
            chain.append(f"afade=t=in:st=0:d={fi:.3f}")
        if fo:
            chain.append(f"afade=t=out:st={max(mdur - fo, 0):.3f}:d={fo:.3f}")
        if start:
            ms = int(start * 1000)
            chain.append(f"adelay={ms}|{ms}")
        graph.append(f"[{idx_in}:a]{','.join(chain)}[{lab}p]")
        if m.get("duck"):
            graph.append(f"[{lab}p][{alabel}]sidechaincompress=threshold=0.06"
                         f":ratio=8:attack=40:release=400:makeup=1[{lab}]")
            # sidechaincompress consumes main; split it first instead
        mix_labels.append(lab if m.get("duck") else f"{lab}p")
        idx_in += 1

    if music:
        # rebuild with a split of the main bus for ducking sidechains
        graph2 = [g for g in graph if "sidechaincompress" not in g]
        duckers = [k for k, m in enumerate(music) if m.get("duck")]
        if duckers:
            outs = "".join(f"[maq{j}]" for j in range(len(duckers)))
            graph2.append(f"[{alabel}]asplit={len(duckers) + 1}[mamain]{outs}")
            main_bus = "mamain"
            for j, k in enumerate(duckers):
                graph2.append(f"[mus{k}p][maq{j}]sidechaincompress=threshold=0.06"
                              f":ratio=8:attack=40:release=400[mus{k}]")
        else:
            main_bus = alabel
        graph = graph2
        mix_in = f"[{main_bus}]" + "".join(f"[{l}]" for l in mix_labels)
        graph.append(f"{mix_in}amix=inputs={len(mix_labels) + 1}"
                     f":duration=first:normalize=0,alimiter=limit=0.97[afinal]")
        alabel = "afinal"

    crf = "28" if mode == "preview" else "18"
    enc_preset = "veryfast" if mode == "preview" else "medium"
    args = inputs + [
        "-filter_complex", ";".join(graph),
        "-map", f"[{vlabel}]", "-map", f"[{alabel}]",
        "-t", f"{total:.4f}",
        "-c:v", "libx264", "-crf", crf, "-preset", enc_preset,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(out),
    ]
    # subtitles filter needs a relative path -> run from project root
    cwd = os.getcwd()
    try:
        os.chdir(root)
        ff.run(args, quiet=quiet)
    finally:
        os.chdir(cwd)
    return out


def export_frames(video_path, times, out_dir, width=640):
    """Extract stills so an agent can look at the edit."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for t in times:
        p = out_dir / f"frame_{t:07.2f}.jpg".replace(".", "_", 1)
        ff.run(["-ss", f"{t:.3f}", "-i", str(video_path), "-frames:v", "1",
                "-vf", f"scale={width}:-2", "-q:v", "5", str(p)])
        paths.append(p)
    return paths
