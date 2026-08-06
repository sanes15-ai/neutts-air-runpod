"""Build the demo project: synthetic media + a timeline that exercises
every engine feature. Run:  python examples/make_demo.py && cd examples/demo
"""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from promptcut import ffmpeg as ff  # noqa: E402

ROOT = Path(__file__).resolve().parent / "demo"
MEDIA = ROOT / "media"


def gen(args):
    subprocess.run([ff.find("ffmpeg"), "-hide_banner", "-v", "error", "-y"] + args,
                   check=True)


def main():
    MEDIA.mkdir(parents=True, exist_ok=True)

    # three visually distinct clips
    gen(["-f", "lavfi", "-i", "testsrc2=duration=6:size=1280x720:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=330:duration=6",
         "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(MEDIA / "scene_a.mp4")])
    gen(["-f", "lavfi", "-i",
         "gradients=duration=6:size=1280x720:rate=30:speed=0.6:"
         "c0=0x0B0B0E:c1=0x3EFFD8:c2=0xFF3E6E",
         "-f", "lavfi", "-i", "sine=frequency=262:duration=6",
         "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(MEDIA / "scene_b.mp4")])
    gen(["-f", "lavfi", "-i", "smptehdbars=duration=6:size=1280x720:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=196:duration=6",
         "-vf", "hue=H=t*0.6",
         "-c:v", "libx264", "-crf", "24", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(MEDIA / "scene_c.mp4")])
    # a small overlay clip (for PiP)
    gen(["-f", "lavfi", "-i", "testsrc=duration=4:size=480x270:rate=30",
         "-c:v", "libx264", "-crf", "26", "-pix_fmt", "yuv420p",
         str(MEDIA / "pip.mp4")])
    # "voice" with silences (tests autocut) and a music bed
    gen(["-f", "lavfi", "-i",
         "aevalsrc=sin(440*2*PI*t)*0.6*lt(mod(t\\,2)\\,1):d=8:s=48000",
         str(MEDIA / "voice.wav")])
    gen(["-f", "lavfi", "-i", "anoisesrc=color=pink:duration=30:amplitude=0.35",
         "-af", "lowpass=f=900",
         str(MEDIA / "music.wav")])

    project = {
        "version": 1,
        "name": "demo",
        "settings": {"width": 1280, "height": 720, "fps": 30,
                     "sample_rate": 48000, "background": "black"},
        "assets": {
            "a": {"path": "media/scene_a.mp4"},
            "b": {"path": "media/scene_b.mp4"},
            "c": {"path": "media/scene_c.mp4"},
            "pip": {"path": "media/pip.mp4"},
            "voice": {"path": "media/voice.wav"},
            "music": {"path": "media/music.wav"},
        },
        "timeline": {
            "video": [
                {"id": "c1", "asset": "a", "in": 0.5, "out": 4.5,
                 "transition_out": {"type": "wipeleft", "duration": 0.6},
                 "color": {"look": "teal_orange", "vignette": 0.4},
                 "transform": {"keyframes": [{"t": 0, "zoom": 1.0},
                                             {"t": 4, "zoom": 1.18}]},
                 "fade_in": 0.4},
                {"id": "c2", "asset": "b", "in": 0.0, "out": 5.0,
                 "ramp": [{"from": 0, "to": 2, "speed": 1.0},
                          {"from": 2, "to": 3, "speed": 0.4},
                          {"from": 3, "to": 5, "speed": 1.4}],
                 "transition_out": {"type": "circleopen", "duration": 0.6},
                 "color": {"look": "vivid"}},
                {"id": "c3", "asset": "c", "in": 1.0, "out": 5.0, "speed": 1.2,
                 "color": {"look": "noir", "grain": 0.4},
                 "fade_out": 0.6},
            ],
            "overlays": [
                {"id": "o1", "asset": "pip", "start": 1.0, "in": 0, "out": 3.0,
                 "x": 0.94, "y": 0.08, "scale": 0.24, "opacity": 0.95,
                 "fade_in": 0.3, "fade_out": 0.3}
            ],
            "texts": [
                {"id": "t1", "text": "PROMPTCUT", "start": 0.6, "end": 3.2,
                 "style": {"size": 92, "color": "white", "y": 0.5, "border": 6},
                 "fade": 0.4},
                {"id": "t2", "text": "edited by prompt", "start": 3.4, "end": 6.0,
                 "style": {"size": 40, "color": "0x3EFFD8", "y": 0.62},
                 "fade": 0.3},
            ],
            "captions": {
                "style": "pop",
                "segments": [
                    {"start": 6.5, "end": 8.2, "text": "cuts transitions ramps"},
                    {"start": 8.4, "end": 10.4, "text": "color looks and captions"},
                ],
            },
            "music": [
                {"id": "m1", "asset": "music", "start": 0, "in": 0, "out": None,
                 "volume": 0.5, "fade_in": 0.8, "fade_out": 1.5, "duck": False}
            ],
        },
    }
    (ROOT / "project.json").write_text(json.dumps(project, indent=2) + "\n")
    print(f"demo ready in {ROOT}")
    print("next: cd examples/demo && promptcut render --preview && promptcut frames")


if __name__ == "__main__":
    main()
