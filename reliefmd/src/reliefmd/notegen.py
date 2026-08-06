"""Note, handout and letter generation with Claude.

Primary backend: the official Anthropic SDK (model: claude-opus-5), with the
system prompt cached and structured output enforced via a JSON schema.
Dev backends: `claude-cli` (uses a local Claude Code login — for development
boxes without an API key) and `mock` (no network at all, for UI tests).
"""

import json
import os
import re
import subprocess

MODEL = os.environ.get("RELIEFMD_MODEL", "claude-opus-5")

SYSTEM = """You are ReliefMD, an expert clinical documentation assistant used by \
physicians and nurse practitioners. You turn a raw doctor-patient visit transcript \
into precise, faithful clinical documentation.

Rules that always apply:
- Document ONLY what is supported by the transcript. Never invent findings, \
vitals, medications, doses, or history that were not said. If something important \
is missing or unclear, put it in the "gaps" list instead of guessing.
- Use standard clinical language and abbreviations in the note; keep the patient \
handout free of jargon.
- Suggested ICD-10 and CPT codes are suggestions for the clinician to verify, \
with honest confidence levels.
- You assist with documentation. You do not diagnose, and the clinician reviews \
and owns every word before it enters the record."""

NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "soap": {
            "type": "object",
            "properties": {
                "subjective": {"type": "string"},
                "objective": {"type": "string"},
                "assessment": {"type": "string"},
                "plan": {"type": "string"},
            },
            "required": ["subjective", "objective", "assessment", "plan"],
            "additionalProperties": False,
        },
        "icd10": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "description": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["code", "description", "confidence"],
                "additionalProperties": False,
            },
        },
        "cpt": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["code", "description"],
                "additionalProperties": False,
            },
        },
        "followups": {"type": "array", "items": {"type": "string"}},
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "patient_handout": {"type": "string"},
    },
    "required": ["soap", "icd10", "cpt", "followups", "red_flags", "gaps",
                 "patient_handout"],
    "additionalProperties": False,
}

# Psychiatry note = base schema + Mental Status Exam + structured risk assessment
_MSE_FIELDS = ["appearance", "behavior", "speech", "mood", "affect",
               "thought_process", "thought_content", "perception",
               "cognition", "insight_judgment"]

PSYCH_SCHEMA = json.loads(json.dumps(NOTE_SCHEMA))
PSYCH_SCHEMA["properties"]["mse"] = {
    "type": "object",
    "properties": {f: {"type": "string"} for f in _MSE_FIELDS},
    "required": _MSE_FIELDS,
    "additionalProperties": False,
}
PSYCH_SCHEMA["properties"]["risk"] = {
    "type": "object",
    "properties": {
        "suicidal_ideation": {"type": "string"},
        "homicidal_ideation": {"type": "string"},
        "self_harm": {"type": "string"},
        "level": {"type": "string", "enum": ["low", "moderate", "high",
                                             "not assessed"]},
        "safety_plan": {"type": "string"},
    },
    "required": ["suicidal_ideation", "homicidal_ideation", "self_harm",
                 "level", "safety_plan"],
    "additionalProperties": False,
}
PSYCH_SCHEMA["required"] = PSYCH_SCHEMA["required"] + ["mse", "risk"]

PSYCH_RULES = """
Additional rules for psychiatric documentation:
- Mental Status Exam: document ONLY what is observable from the transcript \
(speech pattern, expressed mood in the patient's own words in quotes, thought \
content actually voiced). Where the recording gives no evidence for an MSE \
domain, write "not assessed on recording" rather than a normal finding.
- Risk assessment: quote or closely paraphrase what the patient actually said \
about suicidal ideation, homicidal ideation, and self-harm. Never soften or \
upgrade risk beyond the transcript. If risk was not explored, say so in the \
risk fields AND list it under gaps — that is a critical omission.
- Use psychotherapy/E&M CPT codes appropriate to what actually happened \
(e.g. 90791 intake, 90833/90836 add-on therapy, 99212-99215 med management).
- The patient handout should be gentle, stigma-free, and include crisis \
resources placeholder "[local crisis line]" in the warning-signs section."""


def _is_psych(style: str) -> bool:
    return "psych" in (style or "").lower()

LETTER_TYPES = {
    "referral": "a referral letter to a specialist colleague, professional tone, "
                "including reason for referral, relevant history, findings, current "
                "management, and the specific question for the specialist",
    "sick_note": "a short sick note / fitness-for-work certificate stating the "
                 "period of absence and any return-to-work conditions, without "
                 "disclosing the diagnosis unless the transcript says the patient "
                 "consented",
    "insurance": "a letter to an insurance company supporting medical necessity, "
                 "citing the clinical findings and treatment plan",
    "patient_followup": "a warm follow-up letter to the patient summarizing the "
                        "visit, their plan, and when to seek help",
}


class NoteGenError(RuntimeError):
    pass


def backend():
    forced = os.environ.get("RELIEFMD_LLM")
    if forced:
        return forced
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    if os.environ.get("RELIEFMD_MOCK"):
        return "mock"
    return "anthropic"  # SDK also resolves `ant auth login` profiles


def _note_prompt(transcript, style, language, reading_level):
    return f"""Create clinical documentation from this visit transcript.

Note style: {style}. Patient handout language: {language}, written at a \
{reading_level} reading level, formatted as short markdown sections the patient \
can follow at home (what we found, what to do, medicines, warning signs, follow-up).

<transcript>
{transcript}
</transcript>

Return the JSON exactly matching the required schema."""


def generate_note(transcript, style="SOAP", language="English",
                  reading_level="6th grade"):
    b = backend()
    psych = _is_psych(style)
    schema = PSYCH_SCHEMA if psych else NOTE_SCHEMA
    prompt = _note_prompt(transcript, style, language, reading_level)
    if psych:
        prompt += PSYCH_RULES
    if b == "mock":
        return _mock_note(psych)
    if b == "claude-cli":
        raw = _claude_cli(SYSTEM, prompt + "\n\nReturn ONLY the JSON object, no "
                          "markdown fences, matching this JSON schema:\n"
                          + json.dumps(schema))
        return _parse_json(raw)
    return _anthropic_json(prompt, schema)


def generate_letter(transcript, note, letter_type, instructions=""):
    if letter_type not in LETTER_TYPES:
        raise NoteGenError(f"unknown letter type {letter_type!r}; "
                           f"options: {', '.join(LETTER_TYPES)}")
    prompt = f"""Based on the visit below, draft {LETTER_TYPES[letter_type]}.
Use placeholders like [Patient name], [Clinic name], [Date] for anything not in
the transcript — never invent identifying details. {instructions}

<transcript>
{transcript}
</transcript>

<clinical_note>
{json.dumps(note.get('soap', {}), indent=2)}
</clinical_note>

Return only the letter text, ready to review and sign."""
    b = backend()
    if b == "mock":
        return ("[Clinic name]\n[Date]\n\nRe: [Patient name]\n\nThis is a mock "
                f"{letter_type} letter generated in demo mode.\n\n[Clinician name]")
    if b == "claude-cli":
        return _claude_cli(SYSTEM, prompt).strip()
    return _anthropic_text(prompt)


# ---------------------------------------------------------------- backends

def _client():
    import anthropic
    return anthropic.Anthropic()


def _check_refusal(response):
    if response.stop_reason == "refusal":
        detail = ""
        if response.stop_details and getattr(response.stop_details, "explanation", None):
            detail = f" ({response.stop_details.explanation})"
        raise NoteGenError("The model declined this request" + detail)


def _anthropic_json(prompt, schema=NOTE_SCHEMA):
    import anthropic
    try:
        response = _client().messages.create(
            model=MODEL,
            max_tokens=16000,
            system=[{"type": "text", "text": SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError as e:
        raise NoteGenError(
            "Anthropic authentication failed. Set ANTHROPIC_API_KEY on the server "
            "(or RELIEFMD_LLM=mock for a demo without keys).") from e
    except anthropic.APIStatusError as e:
        raise NoteGenError(f"Claude API error {e.status_code}: {e.message}") from e
    _check_refusal(response)
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _anthropic_text(prompt):
    import anthropic
    try:
        response = _client().messages.create(
            model=MODEL,
            max_tokens=8000,
            system=[{"type": "text", "text": SYSTEM,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError as e:
        raise NoteGenError(
            "Anthropic authentication failed. Set ANTHROPIC_API_KEY on the server "
            "(or RELIEFMD_LLM=mock for a demo without keys).") from e
    except anthropic.APIStatusError as e:
        raise NoteGenError(f"Claude API error {e.status_code}: {e.message}") from e
    _check_refusal(response)
    return "".join(b.text for b in response.content if b.type == "text").strip()


def _claude_cli(system, prompt):
    """Dev-only backend: drives the local Claude Code CLI in print mode."""
    try:
        proc = subprocess.run(
            ["claude", "-p", "--output-format", "text",
             "--append-system-prompt", system, prompt],
            capture_output=True, text=True, timeout=600,
        )
    except FileNotFoundError as e:
        raise NoteGenError("claude CLI not found for RELIEFMD_LLM=claude-cli") from e
    if proc.returncode != 0:
        raise NoteGenError(f"claude CLI failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def _parse_json(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise NoteGenError(f"model did not return JSON: {raw[:200]}")
    return json.loads(raw[start:end + 1])


def _mock_note(psych=False):
    note = _mock_note_base()
    if psych:
        note["mse"] = {f: "not assessed on recording" for f in _MSE_FIELDS}
        note["mse"]["mood"] = '"okay, I guess" (patient\'s words)'
        note["risk"] = {"suicidal_ideation": "Denied", "homicidal_ideation": "Denied",
                        "self_harm": "Denied", "level": "low",
                        "safety_plan": "Reviewed crisis line contact."}
    return note


def _mock_note_base():
    return {
        "soap": {
            "subjective": "3 days of sore throat, fever, odynophagia. No cough or "
                          "rhinorrhea.",
            "objective": "T 38.4°C. Erythematous tonsils with exudates, tender "
                         "anterior cervical lymphadenopathy. Chest clear, heart "
                         "sounds normal.",
            "assessment": "Acute pharyngitis, clinically consistent with group A "
                          "streptococcal infection (Centor 4). Rapid strep test "
                          "performed.",
            "plan": "Penicillin V 500 mg BID x10 days. Paracetamol PRN. Off work "
                    "until 24h on antibiotics and afebrile. Safety-netting advised. "
                    "Review in 48h if not improving.",
        },
        "icd10": [
            {"code": "J02.0", "description": "Streptococcal pharyngitis",
             "confidence": "high"},
            {"code": "R50.9", "description": "Fever, unspecified",
             "confidence": "medium"},
        ],
        "cpt": [
            {"code": "99213", "description": "Office visit, established patient, "
                                             "low complexity"},
            {"code": "87880", "description": "Rapid strep antigen test"},
        ],
        "followups": ["Review in 48 hours if not improving",
                      "Confirm rapid strep result documented"],
        "red_flags": ["Difficulty breathing", "Drooling / cannot swallow liquids"],
        "gaps": ["Drug allergy status not discussed on the recording"],
        "patient_handout": "## What we found\nYou have a throat infection that "
            "looks like strep throat.\n\n## What to do\n- Take your antibiotic "
            "(penicillin) twice a day for 10 full days, even if you feel better\n"
            "- Take paracetamol for fever and pain\n- Rest and drink fluids\n\n"
            "## Stay home\nStay off work until you have taken the antibiotic for "
            "24 hours and have no fever.\n\n## Get help right away if\n- You have "
            "trouble breathing or swallowing liquids\n- You are drooling\n\n"
            "## Follow-up\nCome back in 2 days if you are not getting better.",
    }
