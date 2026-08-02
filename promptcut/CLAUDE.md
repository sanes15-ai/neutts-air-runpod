# PromptCut — agent guide

PromptCut is a prompt-driven video editor: `project.json` is the timeline,
`promptcut` (CLI) is the engine. You are the editor — read the skill at
`.claude/skills/promptcut/SKILL.md` for the full schema and recipes.

## The loop

1. `promptcut status` / `promptcut probe <asset>` — know what you have.
2. Edit `project.json` directly (clips, transitions, color, texts, captions,
   music). Times are seconds; positions are 0..1 fractions.
3. `promptcut render --preview` — fast half-res proxy.
4. `promptcut frames --times t1,t2,...` — **look at the stills** and check
   your work (framing, text legibility, transition timing).
5. Iterate, then `promptcut render` for the final.

## Rules

- Never invent asset ids — `promptcut add` registers them; `status` lists them.
- Keep every edit valid: after editing project.json, run `promptcut status`;
  it validates and prints durations.
- Preview before final. Look at frames before declaring success.
- The clip cache (.cache/) makes re-renders cheap — don't clear it casually.
- Tests: `python -m unittest discover tests`. Run them after engine changes.

## Layout

- `src/promptcut/compiler.py` — timeline → ffmpeg filtergraph (two passes)
- `src/promptcut/project.py` — schema, validation, duration math
- `src/promptcut/captions.py` — ASS subtitle/text rendering, SRT, silences
- `src/promptcut/looks.py` — color looks
- `src/promptcut/server.py` + `static/` — self-hosted browser UI
- `examples/make_demo.py` — synthetic end-to-end demo project
