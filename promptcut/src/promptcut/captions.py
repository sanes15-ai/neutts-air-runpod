"""Captions: styled ASS subtitle generation, SRT import, silence detection,
and optional Whisper transcription.

Caption styles (CapCut-template flavored):
  clean   — bottom-centered, bold, soft shadow
  pop     — word-by-word, each word scales in with a bounce
  karaoke — full line visible, words highlight as spoken
  mono    — uppercase terminal style, letterboxed bar
"""

import json
import re
import subprocess
from pathlib import Path

from . import ffmpeg as ff

STYLES = ("clean", "pop", "karaoke", "mono")


def _ts(seconds):
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


NAMED_COLORS = {"white": "FFFFFF", "black": "000000", "red": "FF3030",
                "yellow": "FFE13E", "green": "3EFF7A", "blue": "3E8BFF",
                "cyan": "3EFFD8", "magenta": "FF3ED8", "orange": "FF9A3E"}


def ass_color(value, default="FFFFFF"):
    """'white' | '#RRGGBB' | '0xRRGGBB' -> ASS &H00BBGGRR."""
    v = str(value or default).strip().lower()
    hexv = NAMED_COLORS.get(v)
    if hexv is None:
        v = v.removeprefix("#").removeprefix("0x")
        hexv = v.upper() if re.fullmatch(r"[0-9A-Fa-f]{6}", v) else default
    r, g, b = hexv[0:2], hexv[2:4], hexv[4:6]
    return f"&H00{b}{g}{r}"


def _split_words(seg):
    """Distribute a segment's span across its words (even split fallback)."""
    words = seg.get("words")
    if words:
        return [(float(w["start"]), float(w["end"]), w["text"]) for w in words]
    text = seg["text"].strip()
    parts = text.split()
    if not parts:
        return []
    t0, t1 = float(seg["start"]), float(seg["end"])
    step = (t1 - t0) / len(parts)
    return [(t0 + i * step, t0 + (i + 1) * step, w) for i, w in enumerate(parts)]


def build_ass(proj, root, scale=1.0):
    """Write .cache/overlay.ass with caption segments AND text layers.

    Returns path RELATIVE to root (ffmpeg's subtitles filter is run from there).
    """
    st = proj["settings"]
    W = int(st["width"] * scale) // 2 * 2
    H = int(st["height"] * scale) // 2 * 2
    caps = proj["timeline"].get("captions") or {}
    style = caps.get("style", "clean")
    if style not in STYLES:
        raise ValueError(f"unknown caption style {style!r}; options: {', '.join(STYLES)}")
    segs = caps.get("segments", [])
    texts = proj["timeline"].get("texts") or []
    fs = int(H * 0.058)
    fs_mono = int(H * 0.042)
    font = "DejaVu Sans"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clean,{font},{fs},&H00FFFFFF,&H00FFFFFF,&H00101010,&H7F000000,-1,0,0,0,100,100,0,0,1,{max(2, fs // 16)},{max(2, fs // 14)},2,60,60,{int(H * 0.07)},1
Style: Pop,{font},{int(fs * 1.15)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H7F000000,-1,0,0,0,100,100,1,0,1,{max(3, fs // 12)},0,2,60,60,{int(H * 0.10)},1
Style: Karaoke,{font},{fs},&H00B0B0B0,&H003EFFD8,&H00101010,&H7F000000,-1,0,0,0,100,100,0,0,1,{max(2, fs // 16)},{max(2, fs // 14)},2,60,60,{int(H * 0.07)},1
Style: Mono,{font},{fs_mono},&H003EFFD8,&H003EFFD8,&H00000000,&HA0000000,-1,0,0,0,100,100,{fs_mono // 6},0,3,{max(2, fs_mono // 10)},0,2,40,40,{int(H * 0.06)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if style == "clean":
        for s in segs:
            lines.append(f"Dialogue: 0,{_ts(float(s['start']))},{_ts(float(s['end']))},"
                         f"Clean,,0,0,0,,{s['text'].strip()}")
    elif style == "mono":
        for s in segs:
            lines.append(f"Dialogue: 0,{_ts(float(s['start']))},{_ts(float(s['end']))},"
                         f"Mono,,0,0,0,,{s['text'].strip().upper()}")
    elif style == "pop":
        for s in segs:
            for (w0, w1, word) in _split_words(s):
                fx = r"{\fscx30\fscy30\t(0,90,\fscx118\fscy118)\t(90,160,\fscx100\fscy100)}"
                lines.append(f"Dialogue: 0,{_ts(w0)},{_ts(w1 + 0.02)},Pop,,0,0,0,,{fx}{word}")
    elif style == "karaoke":
        for s in segs:
            words = _split_words(s)
            payload = ""
            for (w0, w1, word) in words:
                payload += r"{\k%d}%s " % (int((w1 - w0) * 100), word)
            lines.append(f"Dialogue: 0,{_ts(float(s['start']))},{_ts(float(s['end']))},"
                         f"Karaoke,,0,0,0,,{payload.strip()}")

    # text layers (titles) — layer 1, absolute-positioned, animated in/out
    for tx in texts:
        sty = tx.get("style") or {}
        stt, ent = float(tx["start"]), float(tx["end"])
        fade_ms = int(float(tx.get("fade") or 0) * 1000)
        size = int(int(sty.get("size", 64)) * scale)
        color = ass_color(sty.get("color", "white"))
        border = int(sty.get("border", 0))
        bcolor = ass_color(sty.get("border_color", "black"), "000000")
        xs = sty.get("x", "center")
        x = W // 2 if xs == "center" else int(W * float(xs))
        y = int(H * float(sty.get("y", 0.85)))
        spacing = int(sty.get("letter_spacing", 0))
        tags = (rf"{{\an5\pos({x},{y})\fs{size}\c{color}\3c{bcolor}"
                rf"\bord{border}\shad2\b1"
                + (rf"\fsp{spacing}" if spacing else "")
                + (rf"\fad({fade_ms},{fade_ms})" if fade_ms else "")
                + "}")
        body = tx["text"].replace("\n", r"\N")
        lines.append(f"Dialogue: 1,{_ts(stt)},{_ts(ent)},Clean,,0,0,0,,{tags}{body}")

    cache = Path(root) / ".cache"
    cache.mkdir(exist_ok=True)
    out = cache / "overlay.ass"
    out.write_text(header + "\n".join(lines) + "\n")
    return ".cache/overlay.ass"


# --------------------------------------------------------------------------
# imports & analysis
# --------------------------------------------------------------------------

SRT_TIME = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt(path):
    """SRT file -> caption segments list."""
    text = Path(path).read_text(errors="replace")
    segments = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = [r.strip() for r in block.strip().splitlines() if r.strip()]
        if len(rows) < 2:
            continue
        m = SRT_TIME.search(rows[0]) or SRT_TIME.search(rows[1] if len(rows) > 1 else "")
        body_idx = 1 if SRT_TIME.search(rows[0]) else 2
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        segments.append({"start": round(start, 3), "end": round(end, 3),
                         "text": " ".join(rows[body_idx:])})
    return segments


def detect_silences(path, noise_db=-32, min_silence=0.45):
    """ffmpeg silencedetect -> [{'start','end'}] silence spans."""
    bin_ = ff.find("ffmpeg")
    proc = subprocess.run(
        [bin_, "-hide_banner", "-i", str(path), "-af",
         f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True)
    spans, start = [], None
    for line in proc.stderr.splitlines():
        if "silence_start:" in line:
            start = float(line.rsplit("silence_start:", 1)[1].strip().split()[0])
        elif "silence_end:" in line and start is not None:
            end = float(line.rsplit("silence_end:", 1)[1].strip().split()[0])
            spans.append({"start": round(start, 3), "end": round(end, 3)})
            start = None
    if start is not None:
        spans.append({"start": round(start, 3), "end": None})
    return spans


def speech_spans(path, noise_db=-32, min_silence=0.45, margin=0.12, min_keep=0.25):
    """Invert silences -> keep-spans of speech/sound, with margins."""
    info = ff.probe(path)
    dur = info["duration"]
    sil = detect_silences(path, noise_db, min_silence)
    keep, cursor = [], 0.0
    for s in sil:
        s_end = s["end"] if s["end"] is not None else dur
        span = (cursor, s["start"] + margin)
        if span[1] - span[0] >= min_keep:
            keep.append({"start": round(max(span[0] - margin, 0), 3),
                         "end": round(min(span[1], dur), 3)})
        cursor = s_end - margin
    if dur - cursor >= min_keep:
        keep.append({"start": round(max(cursor, 0), 3), "end": round(dur, 3)})
    return keep


def transcribe(path, model_size="small", language=None):
    """Optional Whisper transcription (pip install 'promptcut[transcribe]')."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install 'promptcut[transcribe]' "
            "— or bring your own SRT: promptcut captions --srt subs.srt") from e
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(path), language=language, word_timestamps=True)
    out = []
    for seg in segments:
        words = [{"start": w.start, "end": w.end, "text": w.word.strip()}
                 for w in (seg.words or [])]
        out.append({"start": round(seg.start, 3), "end": round(seg.end, 3),
                    "text": seg.text.strip(), "words": words})
    return out
