"""Smoke tests: schema math + a tiny end-to-end render (needs ffmpeg).

Run:  python -m unittest discover tests -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from promptcut import captions as cap  # noqa: E402
from promptcut import compiler, ffmpeg as ff, project as prj  # noqa: E402


class SchemaTests(unittest.TestCase):
    def test_clip_duration_speed(self):
        self.assertAlmostEqual(prj.clip_duration({"id": "c", "in": 0, "out": 4, "speed": 2}), 2.0)

    def test_clip_duration_ramp(self):
        c = {"id": "c", "in": 0, "out": 4,
             "ramp": [{"from": 0, "to": 2, "speed": 1}, {"from": 2, "to": 4, "speed": 0.5}]}
        self.assertAlmostEqual(prj.clip_duration(c), 2 + 4)

    def test_timeline_duration_overlap(self):
        p = prj.new_project("t")
        p["assets"]["a"] = {"path": "x.mp4"}
        p["timeline"]["video"] = [
            {"id": "c1", "asset": "a", "in": 0, "out": 3,
             "transition_out": {"type": "fade", "duration": 0.5}},
            {"id": "c2", "asset": "a", "in": 0, "out": 3},
        ]
        self.assertAlmostEqual(prj.timeline_duration(p), 5.5)

    def test_lerp_expr_constant(self):
        self.assertEqual(compiler.lerp_expr([{"t": 0, "zoom": 1.0}], "zoom", 1.0), "1.000000")

    def test_ass_color(self):
        self.assertEqual(cap.ass_color("white"), "&H00FFFFFF")
        self.assertEqual(cap.ass_color("#3EFFD8"), "&H00D8FF3E")

    def test_srt_parse(self):
        with tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False) as f:
            f.write("1\n00:00:01,000 --> 00:00:02,500\nhello\n\n"
                    "2\n00:00:03,000 --> 00:00:04,000\nworld\n")
        segs = cap.parse_srt(f.name)
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[0]["start"], 1.0)
        self.assertEqual(segs[1]["text"], "world")


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            ff.find("ffmpeg")
        except ff.FFmpegNotFound:
            raise unittest.SkipTest("ffmpeg not available")
        cls.root = Path(tempfile.mkdtemp(prefix="promptcut_test_"))
        media = cls.root / "media"
        media.mkdir()
        subprocess.run([ff.find("ffmpeg"), "-v", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc2=duration=3:size=320x180:rate=15",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                        "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        str(media / "a.mp4")], check=True)
        proj = prj.new_project("t", 320, 180, 15)
        proj["assets"]["a"] = {"path": "media/a.mp4"}
        proj["timeline"]["video"] = [
            {"id": "c1", "asset": "a", "in": 0, "out": 1.5,
             "transition_out": {"type": "fade", "duration": 0.3},
             "color": {"look": "noir"}},
            {"id": "c2", "asset": "a", "in": 1.5, "out": 3.0, "speed": 1.5},
        ]
        proj["timeline"]["texts"] = [
            {"id": "t1", "text": "TEST", "start": 0.2, "end": 1.4,
             "style": {"size": 40, "color": "white", "y": 0.5}, "fade": 0.2}]
        proj["timeline"]["captions"] = {
            "style": "clean",
            "segments": [{"start": 1.6, "end": 2.4, "text": "caption"}]}
        prj.save(proj, cls.root)
        cls.proj = proj

    def test_render_and_frames(self):
        out = compiler.render(self.proj, self.root, mode="preview")
        self.assertTrue(Path(out).exists())
        info = ff.probe(out)
        self.assertGreater(info["duration"], 1.5)
        self.assertTrue(info["has_audio"])
        frames = compiler.export_frames(out, [0.5], self.root / "f")
        self.assertTrue(frames[0].exists())

    def test_silence_tools(self):
        media = self.root / "media" / "v.wav"
        subprocess.run([ff.find("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
                        "aevalsrc=sin(440*2*PI*t)*0.6*lt(mod(t\\,2)\\,1):d=6:s=24000",
                        str(media)], check=True)
        spans = cap.speech_spans(media)
        self.assertGreaterEqual(len(spans), 2)


if __name__ == "__main__":
    unittest.main()
