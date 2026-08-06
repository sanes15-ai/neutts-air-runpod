"""ReliefMD smoke tests — run fully offline via mock mode."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ["RELIEFMD_MOCK"] = "1"
os.environ["RELIEFMD_LLM"] = "mock"
os.environ["RELIEFMD_DATA"] = tempfile.mkdtemp(prefix="reliefmd_test_")

from reliefmd import notegen, transcribe  # noqa: E402


class PipelineTests(unittest.TestCase):
    def test_transcribe_mock(self):
        out = transcribe.transcribe(b"fake-bytes")
        self.assertIn("sore throat", out["text"])
        self.assertEqual(out["provider"], "mock")

    def test_note_shape(self):
        note = notegen.generate_note("transcript")
        for key in ("soap", "icd10", "cpt", "followups", "red_flags",
                    "gaps", "patient_handout"):
            self.assertIn(key, note)
        for section in ("subjective", "objective", "assessment", "plan"):
            self.assertTrue(note["soap"][section])
        self.assertIn(note["icd10"][0]["confidence"], ("high", "medium", "low"))

    def test_letter(self):
        note = notegen.generate_note("t")
        text = notegen.generate_letter("t", note, "sick_note")
        self.assertIn("mock", text.lower())
        with self.assertRaises(notegen.NoteGenError):
            notegen.generate_letter("t", note, "ransom_note")

    def test_json_parse_with_fences(self):
        parsed = notegen._parse_json('```json\n{"a": 1}\n```')
        self.assertEqual(parsed, {"a": 1})


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            raise unittest.SkipTest("httpx not installed for TestClient")
        from reliefmd.app import app
        cls.client = TestClient(app)

    def test_status(self):
        r = self.client.get("/api/status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["llm_backend"], "mock")

    def test_visit_roundtrip_and_letter(self):
        r = self.client.post("/api/visits", data={
            "transcript_text": "Doctor: sore throat three days. Fever 38.4.",
            "patient_label": "Test visit"})
        self.assertEqual(r.status_code, 200, r.text)
        visit = r.json()
        self.assertIn("soap", visit["note"])

        r = self.client.get("/api/visits")
        self.assertTrue(any(v["id"] == visit["id"] for v in r.json()))

        r = self.client.post(f"/api/visits/{visit['id']}/letter",
                             json={"type": "referral"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["text"])

        r = self.client.put(f"/api/visits/{visit['id']}/note",
                            json={"soap": {"plan": "edited plan"}})
        self.assertEqual(r.status_code, 200)
        r = self.client.get(f"/api/visits/{visit['id']}")
        self.assertEqual(r.json()["note"]["soap"]["plan"], "edited plan")


if __name__ == "__main__":
    unittest.main()
