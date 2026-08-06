# PromptCut

**A video editor where the editor is a conversation.**

PromptCut has no proprietary project format, no locked-in UI, and no
mouse-marathon workflows. A project is a plain **JSON timeline** that
[Claude Code](https://claude.com/claude-code) (or you) edits directly, and a
Python engine compiles it into ffmpeg render graphs. A self-hosted browser UI
is included for visual review and hand-tweaks.

```
"cut the silences, punch in 10% on every talking-head shot,
 add pop captions, teal-orange grade, duck the music under my voice,
 and give me a 9:16 cut for reels"
```

…is a prompt, not an afternoon.

## Install

```bash
pip install -e .
./scripts/get_ffmpeg.sh        # or: brew install ffmpeg / apt install ffmpeg
promptcut doctor               # check everything is green
```

## 60-second tour

```bash
mkdir my-edit && cd my-edit
promptcut new my-edit --size 1920x1080 --fps 30
promptcut add ~/footage/*.mp4 ~/music/track.mp3
promptcut status                       # timeline summary as JSON
# edit project.json (by hand, by prompt, or in the browser UI)
promptcut render --preview             # fast half-res proxy
promptcut frames --times 2,5,9         # stills an agent can look at
promptcut render                       # final export
promptcut serve                        # browser UI at localhost:7859
```

Try the demo: `python examples/make_demo.py && cd examples/demo && promptcut render --preview`

## What it does today (v0.1)

| Area | Features |
|---|---|
| **Cutting** | trim, split, reorder, multi-clip timeline, `autocut` (silence removal with margins) |
| **Transitions** | 25+ (fade, dissolve, wipes, slides, circle, radial, pixelize, zoom, …) via `xfade` + audio crossfades |
| **Speed** | constant speed, **speed ramps** (segmented velocity curves), pitch-corrected audio |
| **Motion** | keyframed **pan/zoom (Ken Burns)** with supersampled crops, rotate, flip |
| **Color** | 10 built-in looks (teal_orange, noir, vintage, cinema, vivid, …), **.cube LUTs**, exposure/contrast/saturation/temperature, vignette, grain, sharpen |
| **Text** | styled titles with fades, positioning, borders (rendered by libass) |
| **Captions** | 4 styles incl. **word-by-word pop** and karaoke; SRT import; optional Whisper transcription; ffmpeg silence detection |
| **Layers** | picture-in-picture overlays, **chromakey** (green screen), opacity, fades |
| **Audio** | multi-track music, volume, fades, looping, **sidechain ducking** under the main track |
| **Output** | H.264 MP4 presets, fast half-res previews, frame extraction for agent review, incremental clip cache |
| **UI** | self-hosted browser app: timeline, clip inspector, transitions/looks pickers, render + preview player |

## Honesty section: vs CapCut / Premiere / DaVinci

"Everything they have" is a multi-year roadmap — here is the real map.
What PromptCut already covers is the practical core of CapCut and a useful
slice of Premiere; its superpower is that **an AI agent can operate 100% of
it**, which none of the big three can say.

| Capability | CapCut | Premiere | DaVinci | PromptCut |
|---|---|---|---|---|
| Cuts / trims / timeline | ✅ | ✅ | ✅ | ✅ |
| Transitions | ✅ | ✅ | ✅ | ✅ 25+ |
| Auto-captions | ✅ | ✅ | ✅ | ✅ (Whisper opt-in / SRT) |
| Silence removal | ✅ | ➖ | ➖ | ✅ |
| Speed ramps | ✅ | ✅ | ✅ | ✅ segmented |
| Keyframed motion | ✅ | ✅ | ✅ | ✅ pan/zoom/rotate |
| Color looks + LUTs | ✅ | ✅ | ✅✅ | ✅ |
| Green screen | ✅ | ✅ | ✅ | ✅ |
| Audio ducking | ✅ | ✅ | ✅ | ✅ |
| Edit by natural language | ➖ | ➖ | ➖ | ✅✅ **the whole point** |
| Scriptable/versionable projects | ➖ | ➖ | ➖ | ✅ plain JSON in git |
| Motion tracking | ✅ | ✅ | ✅ | 🔜 roadmap |
| Masks / rotoscoping | ➖ | ✅ | ✅ | 🔜 roadmap |
| Multicam | ➖ | ✅ | ✅ | 🔜 roadmap |
| Node compositing (Fusion) | ➖ | ➖ | ✅ | ❌ out of scope |
| Pro audio suite (Fairlight) | ➖ | ➖ | ✅ | ❌ out of scope |
| Realtime GPU preview | ✅ | ✅ | ✅ | ➖ proxy renders instead |

## Using it with Claude Code

The repo ships a skill (`.claude/skills/promptcut/`) that teaches Claude the
schema and workflow. Open this repo (or any project folder) in Claude Code and
say what you want:

> "make a 30-second cut of interview.mp4, remove the silences, karaoke
> captions, noir look on the b-roll, export 9:16"

Claude runs `promptcut` commands, edits `project.json`, renders previews,
**looks at the frames**, and iterates — the same loop a human editor runs.

## Architecture

```
project.json  ──►  compiler.py ──► pass 1: per-clip normalized intermediates
   ▲                  │             (trim+speed+color+motion baked, cached by hash)
   │                  └──────────► pass 2: xfade/concat chain + overlays
Claude Code / UI / you                     + libass text&captions + audio mix ──► mp4
```

No dependencies beyond Python 3.9+ and ffmpeg. Whisper transcription is an
optional extra: `pip install 'promptcut[transcribe]'`.

## License

MIT
