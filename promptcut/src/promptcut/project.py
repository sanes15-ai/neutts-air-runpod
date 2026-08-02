"""Project (timeline) schema: load, validate, save, and computed durations.

A project is a plain JSON file an agent edits directly. Schema (v1):

{
  "version": 1,
  "name": "my-edit",
  "settings": {"width":1920,"height":1080,"fps":30,"sample_rate":48000,"background":"black"},
  "assets": {"a1": {"path": "media/clip.mp4"}},
  "timeline": {
    "video": [            # main track — clips play sequentially
      {"id":"c1","asset":"a1","in":2.0,"out":7.5,
       "speed":1.0,                                # or "ramp":[{"from":0,"to":2,"speed":1},{"from":2,"to":5.5,"speed":0.4}]
       "fit":"cover",                              # cover|contain
       "transition_out":{"type":"fade","duration":0.5},
       "color":{"look":"teal_orange","exposure":0,"contrast":1,"saturation":1,
                "temperature":0,"lut":null,"vignette":0,"grain":0,"sharpen":0},
       "transform":{"keyframes":[{"t":0,"zoom":1.0,"x":0.5,"y":0.5},{"t":5,"zoom":1.15}]},
       "rotate":0, "flip":null,                    # flip: "h"|"v"
       "fade_in":0,"fade_out":0,                   # video opacity fades (sec)
       "audio":{"volume":1.0,"mute":false,"fade_in":0,"fade_out":0}}
    ],
    "overlays": [          # picture-in-picture layers, absolute timeline time
      {"id":"o1","asset":"a2","start":3.0,"in":0,"out":4.0,
       "x":0.7,"y":0.1,"scale":0.3,"opacity":1.0,"rounded":0,
       "chromakey":{"color":"0x00d000","similarity":0.18,"blend":0.08},
       "fade_in":0.3,"fade_out":0.3,"audio":{"volume":0,"mute":true}}
    ],
    "texts": [
      {"id":"t1","text":"HELLO","start":0.5,"end":3.5,
       "style":{"size":72,"color":"white","font_file":null,"border":6,
                "border_color":"black","x":"center","y":0.82,"box":false,
                "box_color":"black@0.5","letter_spacing":0},
       "fade":0.3}
    ],
    "captions": {"style":"clean","segments":[{"start":1.0,"end":2.2,"text":"hello world"}]},
    "music": [
      {"id":"m1","asset":"m1","start":0,"in":0,"out":null,
       "volume":0.8,"fade_in":1,"fade_out":2,"duck":true,"loop":false}
    ]
  }
}

Times are seconds. x/y positions are fractions of frame (0..1) unless noted.
"""

import copy
import json
from pathlib import Path

PROJECT_FILE = "project.json"

DEFAULT_SETTINGS = {"width": 1920, "height": 1080, "fps": 30,
                    "sample_rate": 48000, "background": "black"}

DEFAULT_COLOR = {"look": None, "exposure": 0.0, "contrast": 1.0, "saturation": 1.0,
                 "temperature": 0.0, "lut": None, "vignette": 0.0, "grain": 0.0,
                 "sharpen": 0.0}

DEFAULT_AUDIO = {"volume": 1.0, "mute": False, "fade_in": 0.0, "fade_out": 0.0}

TRANSITIONS = {  # name -> ffmpeg xfade transition
    "fade": "fade", "crossfade": "fade", "dissolve": "dissolve",
    "wipeleft": "wipeleft", "wiperight": "wiperight", "wipeup": "wipeup",
    "wipedown": "wipedown", "slideleft": "slideleft", "slideright": "slideright",
    "slideup": "slideup", "slidedown": "slidedown", "circleopen": "circleopen",
    "circleclose": "circleclose", "radial": "radial", "smoothleft": "smoothleft",
    "smoothright": "smoothright", "pixelize": "pixelize", "distance": "distance",
    "fadeblack": "fadeblack", "fadewhite": "fadewhite", "zoomin": "zoomin",
    "squeezeh": "squeezeh", "squeezev": "squeezev", "hlwind": "hlwind",
    "coverleft": "coverleft", "coverright": "coverright",
}


class ProjectError(ValueError):
    pass


def new_project(name, width=1920, height=1080, fps=30):
    return {
        "version": 1,
        "name": name,
        "settings": {**DEFAULT_SETTINGS, "width": width, "height": height, "fps": fps},
        "assets": {},
        "timeline": {"video": [], "overlays": [], "texts": [],
                     "captions": {"style": "clean", "segments": []}, "music": []},
    }


def load(root):
    p = Path(root) / PROJECT_FILE
    if not p.exists():
        raise ProjectError(f"No {PROJECT_FILE} in {root}. Run: promptcut new <name>")
    proj = json.loads(p.read_text())
    validate(proj, root)
    return proj


def save(proj, root):
    p = Path(root) / PROJECT_FILE
    p.write_text(json.dumps(proj, indent=2) + "\n")
    return p


def clip_source_span(clip):
    if clip.get("out") is None or clip.get("in") is None:
        raise ProjectError(f"clip {clip.get('id')}: needs numeric in/out")
    span = float(clip["out"]) - float(clip["in"])
    if span <= 0:
        raise ProjectError(f"clip {clip.get('id')}: out must be > in")
    return span


def clip_duration(clip):
    """Output duration after speed/ramp."""
    span = clip_source_span(clip)
    ramp = clip.get("ramp")
    if ramp:
        total = 0.0
        for seg in ramp:
            seg_span = float(seg["to"]) - float(seg["from"])
            if seg_span <= 0 or float(seg["speed"]) <= 0:
                raise ProjectError(f"clip {clip.get('id')}: bad ramp segment {seg}")
            total += seg_span / float(seg["speed"])
        return total
    speed = float(clip.get("speed", 1.0) or 1.0)
    if speed <= 0:
        raise ProjectError(f"clip {clip.get('id')}: speed must be > 0")
    return span / speed


def timeline_duration(proj):
    """Main-track duration accounting for transition overlaps."""
    clips = proj["timeline"]["video"]
    total = 0.0
    for i, c in enumerate(clips):
        total += clip_duration(c)
        if i < len(clips) - 1:
            tr = c.get("transition_out")
            if tr:
                total -= float(tr.get("duration", 0.5))
    return max(total, 0.0)


def clip_start_times(proj):
    """Timeline start time of each main-track clip (transition overlaps included)."""
    starts, t = [], 0.0
    clips = proj["timeline"]["video"]
    for i, c in enumerate(clips):
        starts.append(t)
        t += clip_duration(c)
        if i < len(clips) - 1 and c.get("transition_out"):
            t -= float(c["transition_out"].get("duration", 0.5))
    return starts


def validate(proj, root=None):
    if not isinstance(proj, dict) or "timeline" in proj is None:
        raise ProjectError("project.json must be an object with a timeline")
    proj.setdefault("settings", {})
    for k, v in DEFAULT_SETTINGS.items():
        proj["settings"].setdefault(k, v)
    tl = proj.setdefault("timeline", {})
    for key, default in (("video", []), ("overlays", []), ("texts", []), ("music", [])):
        tl.setdefault(key, default)
    tl.setdefault("captions", {"style": "clean", "segments": []})

    ids = set()
    for section in ("video", "overlays", "texts", "music"):
        for item in tl[section]:
            iid = item.get("id")
            if not iid or iid in ids:
                raise ProjectError(f"{section}: every item needs a unique id (got {iid!r})")
            ids.add(iid)

    for section in ("video", "overlays", "music"):
        for item in tl[section]:
            aid = item.get("asset")
            if aid not in proj.get("assets", {}):
                raise ProjectError(f"{section} item {item['id']}: unknown asset {aid!r}")

    if root:
        for aid, a in proj.get("assets", {}).items():
            path = Path(root) / a["path"]
            if not path.exists():
                raise ProjectError(f"asset {aid}: file not found: {path}")

    for c in tl["video"]:
        clip_duration(c)  # raises on bad numbers
        tr = c.get("transition_out")
        if tr and tr.get("type") not in TRANSITIONS:
            raise ProjectError(
                f"clip {c['id']}: unknown transition {tr.get('type')!r}. "
                f"Options: {', '.join(sorted(TRANSITIONS))}")
    return proj


def merged_color(clip):
    c = copy.deepcopy(DEFAULT_COLOR)
    c.update(clip.get("color") or {})
    return c


def merged_audio(clip):
    a = copy.deepcopy(DEFAULT_AUDIO)
    a.update(clip.get("audio") or {})
    return a
