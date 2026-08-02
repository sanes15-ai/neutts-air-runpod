---
name: promptcut
description: Edit videos by prompt with PromptCut — create/modify the project.json timeline, run promptcut CLI commands (add, autocut, captions, render, frames), and visually verify renders. Use whenever the user asks to edit, cut, caption, grade, or export video in a PromptCut project.
---

# PromptCut editing skill

You are the video editor. The timeline is `project.json`; the engine is the
`promptcut` CLI. Always follow the loop: **inspect → edit → preview → look at
frames → iterate → final render**.

## Commands

```bash
promptcut new <name> [--size 1920x1080] [--fps 30]   # create project in cwd
promptcut add <files...> [--link]                    # import media, prints probe info
promptcut probe <asset-or-file>                      # duration/resolution/audio
promptcut status                                     # validated timeline summary
promptcut silences <asset> [--noise -32]             # silence + speech spans JSON
promptcut autocut <asset> [--noise -32 --margin 0.12]# rebuild track minus silences
promptcut captions --srt subs.srt --style pop        # or --transcribe <asset>
promptcut render --preview                           # half-res proxy in render/
promptcut render                                     # final render
promptcut frames --times 1.5,4,9 [--width 640]       # stills → .cache/frames/
promptcut looks                                      # list looks/transitions/styles
promptcut serve --port 7859                          # browser UI for the human
promptcut doctor                                     # env check
```

## project.json essentials

Main track = `timeline.video` (sequential). All times in seconds.

```jsonc
{"id":"c1","asset":"a1","in":2.0,"out":7.5,          // trim from source
 "speed":1.0,                                         // or ramp (below)
 "ramp":[{"from":0,"to":2,"speed":1},{"from":2,"to":4,"speed":0.4}],
 "transition_out":{"type":"wipeleft","duration":0.5}, // to the NEXT clip
 "color":{"look":"teal_orange","contrast":1.05,"saturation":1.1,
          "temperature":15,"vignette":0.3,"grain":0.2,"lut":"luts/film.cube"},
 "transform":{"keyframes":[{"t":0,"zoom":1},{"t":4,"zoom":1.15,"x":0.6,"y":0.4}]},
 "fade_in":0.4,"fade_out":0.4,
 "audio":{"volume":1.0,"mute":false}}
```

- `transform` keyframes: `zoom` ≥1, `x`/`y` = pan center (0..1). Lerped.
- `overlays`: PiP with `start`, `in/out`, `x/y/scale`, `opacity`,
  `chromakey:{color,similarity,blend}` for green screen.
- `texts`: `{text,start,end,style:{size,color,y,border},fade}`.
- `captions`: `{style:"clean|pop|karaoke|mono", segments:[{start,end,text}]}`.
- `music`: `{asset,start,volume,fade_in,fade_out,duck:true,loop}` — `duck`
  sidechains music under the main track audio.
- Looks: `promptcut looks` lists everything valid.

## Recipes

- **Talking-head cleanup**: `autocut voice_asset` → review `status` →
  `captions --transcribe voice_asset --style pop` → preview.
- **Reel from long video**: pick moments with `probe`+`silences`, build 3–6
  clips with transitions, `settings` 1080x1920, zoom keyframes for punch-ins.
- **B-roll montage**: 2–4s clips, alternating transitions, one look across
  all clips, music with `duck:false`, `fade_out` on the last clip.

## Verification (mandatory)

After `render --preview`, run `promptcut frames` at moments you changed
(mid-transition, caption times, overlay windows) and **Read the JPGs**. Check:
text inside frame and legible, transitions at the right time, grade looks
intentional, PiP not covering faces. Fix and re-preview before final render.
Renders are incremental — only changed clips recompile.
