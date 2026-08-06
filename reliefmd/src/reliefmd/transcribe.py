"""Transcription provider chain — premium APIs first, local fallback, mock for dev.

Order of preference (first configured wins):
  1. Deepgram Nova-3 Medical  (DEEPGRAM_API_KEY)  — purpose-built clinical vocabulary
  2. OpenAI transcription     (OPENAI_API_KEY)    — gpt-4o-transcribe
  3. faster-whisper           (pip install 'reliefmd[local-transcribe]') — offline
  4. mock                     (RELIEFMD_MOCK=1)   — canned consult, for UI/dev only
"""

import json
import os
import urllib.request
import uuid


class TranscriptionError(RuntimeError):
    pass


MOCK_TRANSCRIPT = (
    "Doctor: Good morning, what brings you in today? "
    "Patient: I've had a sore throat and fever for three days, and it hurts to swallow. "
    "Doctor: Any cough or runny nose? Patient: No cough, no runny nose. "
    "Doctor: Let me have a look. Your temperature today is 38.4. Throat shows red, "
    "swollen tonsils with white patches, and I can feel tender lymph nodes in your neck. "
    "Heart and lungs sound clear. Doctor: This looks like strep throat. I'll do a rapid "
    "strep test to confirm. Given the classic picture I'll start you on penicillin V, "
    "500 milligrams twice daily for ten days. Take paracetamol for the fever and pain. "
    "Patient: Can I go to work? Doctor: Stay home until you've been on antibiotics for "
    "24 hours and are fever free. If you develop difficulty breathing, drooling, or "
    "can't swallow liquids, go to the emergency department immediately. Come back if "
    "you're not improving in 48 hours. I'll also give you a sick note for two days."
)


def active_provider():
    if os.environ.get("DEEPGRAM_API_KEY"):
        return "deepgram"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    try:
        import faster_whisper  # noqa: F401
        return "local-whisper"
    except ImportError:
        pass
    if os.environ.get("RELIEFMD_MOCK"):
        return "mock"
    return None


def transcribe(audio_bytes: bytes, mime: str = "audio/webm", language: str | None = None) -> dict:
    """Returns {"text": ..., "provider": ...}. Raises TranscriptionError if no provider."""
    provider = active_provider()
    if provider == "deepgram":
        return _deepgram(audio_bytes, mime, language)
    if provider == "openai":
        return _openai(audio_bytes, mime, language)
    if provider == "local-whisper":
        return _local_whisper(audio_bytes, language)
    if provider == "mock":
        return {"text": MOCK_TRANSCRIPT, "provider": "mock"}
    raise TranscriptionError(
        "No transcription provider configured. Set DEEPGRAM_API_KEY (recommended, "
        "medical model) or OPENAI_API_KEY, or install the local fallback: "
        "pip install 'reliefmd[local-transcribe]'"
    )


def _deepgram(audio_bytes, mime, language):
    params = "model=nova-3-medical&smart_format=true&punctuate=true&diarize=true"
    if language:
        params += f"&language={language}"
    req = urllib.request.Request(
        f"https://api.deepgram.com/v1/listen?{params}",
        data=audio_bytes,
        headers={
            "Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}",
            "Content-Type": mime,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        raise TranscriptionError(f"Deepgram request failed: {e}") from e
    try:
        alt = data["results"]["channels"][0]["alternatives"][0]
        text = alt.get("paragraphs", {}).get("transcript") or alt["transcript"]
    except (KeyError, IndexError) as e:
        raise TranscriptionError(f"Unexpected Deepgram response: {e}") from e
    return {"text": text.strip(), "provider": "deepgram-nova-3-medical"}


def _openai(audio_bytes, mime, language):
    boundary = uuid.uuid4().hex
    ext = "webm" if "webm" in mime else ("mp3" if "mp3" in mime or "mpeg" in mime else "wav")
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\ngpt-4o-transcribe\r\n",
    ]
    if language:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\n{language}\r\n")
    body = "".join(parts).encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"audio.{ext}\"\r\nContent-Type: {mime}\r\n\r\n").encode()
    body += audio_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/transcriptions",
        data=body,
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        raise TranscriptionError(f"OpenAI transcription failed: {e}") from e
    return {"text": data.get("text", "").strip(), "provider": "openai-gpt-4o-transcribe"}


def _local_whisper(audio_bytes, language):
    import tempfile
    from faster_whisper import WhisperModel

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        f.write(audio_bytes)
        path = f.name
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"),
                         device="cpu", compute_type="int8")
    segments, _info = model.transcribe(path, language=language)
    text = " ".join(s.text.strip() for s in segments)
    os.unlink(path)
    return {"text": text.strip(), "provider": "local-faster-whisper"}
