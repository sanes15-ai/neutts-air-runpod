# ReliefMD

**The scribe that gives clinicians their evenings back.**

Record a patient visit (or upload audio / paste a transcript). ReliefMD
transcribes it with a premium medical speech API, then Claude writes:

- a **SOAP note** ready to copy into any EHR (editable in place)
- **ICD-10 + CPT suggestions** with honest confidence levels
- a **plain-language patient handout** in the patient's language, at a
  6th-grade reading level
- a **"don't miss" list** — follow-ups, safety-netting, and *gaps* the
  recording never covered (allergies not asked, etc.)
- **letters from the doctor, on demand**: referral letter, sick note,
  insurance letter, patient follow-up letter — one click each

The clinician reviews and edits everything before it goes anywhere.
ReliefMD is documentation assistance, **not a medical device**.

## Quickstart

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...          # note generation (Claude)
export DEEPGRAM_API_KEY=...                  # premium medical transcription
export RELIEFMD_TOKEN=$(openssl rand -hex 16)
reliefmd                                     # → http://127.0.0.1:7870/?token=...
```

No keys yet? `RELIEFMD_MOCK=1 reliefmd` runs a full demo pipeline offline.

## Architecture

```
browser mic ──► FastAPI ──► transcription chain ──► Claude (claude-opus-5)
 (MediaRecorder)             1. Deepgram Nova-3 Medical   structured JSON note
                             2. OpenAI gpt-4o-transcribe  + handout + letters
                             3. local faster-whisper
                             4. mock (dev)
```

- **Transcription** (`transcribe.py`): premium APIs first — Deepgram's
  Nova-3 *Medical* model is purpose-built for clinical vocabulary. Falls
  back to OpenAI, then a local Whisper install, then mock.
- **Generation** (`notegen.py`): the official Anthropic SDK with
  `claude-opus-5`, a cached system prompt, a strict JSON schema for the
  note (no parse failures), and refusal handling. `RELIEFMD_LLM=claude-cli`
  exists for development boxes that have a Claude Code login but no API key.
- **Storage** (`app.py`): visits are JSON files under `data/` on *your*
  server. **Audio is discarded after transcription** unless
  `RELIEFMD_KEEP_AUDIO=1`. Token auth on every route.

## Configuration

| Env var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude — note/handout/letter generation |
| `DEEPGRAM_API_KEY` | Premium medical transcription (recommended) |
| `OPENAI_API_KEY` | Alternate transcription |
| `RELIEFMD_TOKEN` | Access token — required for any non-local hosting |
| `RELIEFMD_HOST` / `PORT` | Bind address (default 127.0.0.1:7870) |
| `RELIEFMD_MODEL` | Claude model override (default `claude-opus-5`) |
| `RELIEFMD_DATA` | Data directory (default `./data`) |
| `RELIEFMD_KEEP_AUDIO` | `1` keeps audio files (default: delete) |
| `RELIEFMD_MOCK` | `1` = offline demo mode |
| `RELIEFMD_LLM` | Force backend: `anthropic` / `claude-cli` / `mock` |

## Compliance homework (read before real patient data)

- Patient audio and notes are PHI. Host on infrastructure you control,
  behind HTTPS (put Caddy/nginx in front), with the token set.
- Deepgram, OpenAI, and Anthropic all offer agreements covering healthcare
  workloads (e.g. BAAs) on qualifying plans — **sign them before production
  use**, or self-host transcription (`pip install 'reliefmd[local-transcribe]'`)
  to keep audio on your box.
- Default behavior is privacy-first: audio deleted after transcription,
  nothing leaves your server except the API calls you configured.

## Tests

```bash
python -m unittest discover tests -v
```
