# VANTA//APEX — PPF brand website

A motion-graphics-heavy single-page site for a fictional paint protection
film / car wrapping brand. Bold racing energy: GSAP + ScrollTrigger +
SplitText + Lenis smooth scroll, zero build step.

## Run it

```bash
cd website
python3 -m http.server 8321
# open http://localhost:8321
```

Opening `index.html` directly via `file://` also works (fonts and GSAP load
from CDNs, so you need to be online either way).

## The centerpiece

**THE FINISH** section scroll-scrubs 200 JPEG frames of real neon-lit
bodywork footage on a `<canvas>` — as you scroll, the neon reflections on
the black paint shift from magenta to green, and the HUD accent color,
phase words (EXPOSED → ARMORED) and spec callouts sync to it.

## Motion inventory

- Preloader with real frame-preload progress + diagonal curtain wipe
- Hero: SplitText char cascade, video settle, parallax-out
- Dual velocity-reactive marquees (speed + skew follow scroll velocity)
- Pinned 400vh canvas frame scrub with HUD choreography
- Services: clip-path card wipes, hover-play videos, 3D tilt, magnetic arrows
- Process: pinned horizontal scroll with telemetry bar + numeral parallax
- Stat count-ups, showcase window-expand + video parallax, quote word stagger
- Magnetic CTA, custom volt cursor, footer logotype rise + fill sweep

Falls back gracefully: `prefers-reduced-motion` gets a static, native-scroll
page; touch devices skip cursor/magnetic/tilt; mobile stacks the process
section and shortens the scrub.

## Assets

All footage is free-license stock from Pexels (see `assets/CREDITS.md`).
Regenerate everything with `tools/fetch_assets.sh` (needs ffmpeg + curl).
