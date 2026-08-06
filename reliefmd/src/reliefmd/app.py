"""ReliefMD server — FastAPI app serving the UI and the visit pipeline."""

import datetime
import json
import os
import secrets
import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, notegen, transcribe as tr

STATIC = Path(__file__).parent / "static"
DATA = Path(os.environ.get("RELIEFMD_DATA", "data")).resolve()
TOKEN = os.environ.get("RELIEFMD_TOKEN") or None
KEEP_AUDIO = os.environ.get("RELIEFMD_KEEP_AUDIO") == "1"

app = FastAPI(title="ReliefMD", version=__version__)


# ------------------------------------------------------------------ auth

@app.middleware("http")
async def auth(request: Request, call_next):
    if TOKEN:
        supplied = (request.query_params.get("token")
                    or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
                    or request.cookies.get("rmd_token"))
        if not (supplied and secrets.compare_digest(supplied, TOKEN)):
            return JSONResponse({"error": "unauthorized — open /?token=YOUR_TOKEN"},
                                status_code=401)
    response = await call_next(request)
    if TOKEN and request.query_params.get("token"):
        response.set_cookie("rmd_token", TOKEN, httponly=True, samesite="strict")
    return response


# ------------------------------------------------------------------ storage

def _visits_dir():
    d = DATA / "visits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(visit_id):
    p = _visits_dir() / f"{visit_id}.json"
    if not p.exists():
        raise HTTPException(404, "visit not found")
    return json.loads(p.read_text())


def _save(visit):
    (_visits_dir() / f"{visit['id']}.json").write_text(json.dumps(visit, indent=2))


# ------------------------------------------------------------------ routes

@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
async def status():
    return {
        "version": __version__,
        "transcription": tr.active_provider() or "NOT CONFIGURED",
        "llm_backend": notegen.backend(),
        "model": notegen.MODEL,
        "auth": bool(TOKEN),
        "visits": len(list(_visits_dir().glob("*.json"))),
    }


@app.post("/api/visits")
async def create_visit(
    audio: UploadFile = File(None),
    transcript_text: str = Form(None),
    style: str = Form("SOAP"),
    language: str = Form("English"),
    reading_level: str = Form("6th grade"),
    patient_label: str = Form(""),
):
    visit_id = uuid.uuid4().hex[:12]
    if transcript_text:
        transcript = {"text": transcript_text.strip(), "provider": "typed"}
    elif audio is not None:
        blob = await audio.read()
        if not blob:
            raise HTTPException(400, "empty audio upload")
        if KEEP_AUDIO:
            adir = DATA / "audio"
            adir.mkdir(parents=True, exist_ok=True)
            (adir / f"{visit_id}.webm").write_bytes(blob)
        try:
            transcript = tr.transcribe(blob, audio.content_type or "audio/webm")
        except tr.TranscriptionError as e:
            raise HTTPException(503, str(e)) from e
        # audio is discarded here unless RELIEFMD_KEEP_AUDIO=1 — privacy default
    else:
        raise HTTPException(400, "provide an audio file or transcript_text")

    try:
        note = notegen.generate_note(transcript["text"], style, language, reading_level)
    except notegen.NoteGenError as e:
        raise HTTPException(503, str(e)) from e

    visit = {
        "id": visit_id,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "patient_label": patient_label.strip() or "Unlabeled visit",
        "style": style,
        "language": language,
        "transcript": transcript,
        "note": note,
        "letters": {},
    }
    _save(visit)
    return visit


@app.get("/api/visits")
async def list_visits():
    out = []
    for p in sorted(_visits_dir().glob("*.json"), reverse=True):
        v = json.loads(p.read_text())
        out.append({"id": v["id"], "created_at": v["created_at"],
                    "patient_label": v["patient_label"],
                    "assessment": v["note"]["soap"]["assessment"][:120]})
    return out


@app.get("/api/visits/{visit_id}")
async def get_visit(visit_id: str):
    return _load(visit_id)


@app.put("/api/visits/{visit_id}/note")
async def update_note(visit_id: str, request: Request):
    visit = _load(visit_id)
    body = await request.json()
    if "soap" in body:
        visit["note"]["soap"].update(body["soap"])
    if "patient_handout" in body:
        visit["note"]["patient_handout"] = body["patient_handout"]
    _save(visit)
    return {"saved": True}


@app.post("/api/visits/{visit_id}/letter")
async def make_letter(visit_id: str, request: Request):
    visit = _load(visit_id)
    body = await request.json()
    letter_type = body.get("type", "referral")
    try:
        text = notegen.generate_letter(visit["transcript"]["text"], visit["note"],
                                       letter_type, body.get("instructions", ""))
    except notegen.NoteGenError as e:
        raise HTTPException(503, str(e)) from e
    visit["letters"][letter_type] = text
    _save(visit)
    return {"type": letter_type, "text": text}


@app.delete("/api/visits/{visit_id}")
async def delete_visit(visit_id: str):
    p = _visits_dir() / f"{visit_id}.json"
    if p.exists():
        p.unlink()
    return {"deleted": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def main():
    host = os.environ.get("RELIEFMD_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "7870"))
    if host not in ("127.0.0.1", "localhost") and not TOKEN:
        print("WARNING: serving on a public interface without RELIEFMD_TOKEN — "
              "visit data would be open to anyone. Set RELIEFMD_TOKEN.")
    url = f"http://{host}:{port}" + (f"/?token={TOKEN}" if TOKEN else "")
    print(f"ReliefMD → {url}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
