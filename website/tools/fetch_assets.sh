#!/usr/bin/env bash
# Regenerates website/assets from Pexels sources. Requires ffmpeg and curl.
# Usage: ./tools/fetch_assets.sh  (run from website/ root)
set -euo pipefail

RAW="$(mktemp -d)"
FF="${FFMPEG:-ffmpeg}"

# clip ids: hero corvette, scrub neon-gloss, showcase skyline, hovers (water/roof/buffing)
for id in 33374863 8470710 30391331 16818471 6159287 6159290; do
  curl -sL "https://www.pexels.com/download/video/${id}/" -o "$RAW/${id}.mp4"
done

mkdir -p assets/video assets/frames/peel assets/img

enc() { # enc <in> <out> <height> <crf> [extra input args...]
  local in="$1" out="$2" h="$3" crf="$4"; shift 4
  "$FF" -y -v error "$@" -i "$in" -an -vf "scale=-2:${h},fps=24" \
    -c:v libx264 -crf "$crf" -preset slow -pix_fmt yuv420p \
    -movflags +faststart "$out"
}

enc "$RAW/33374863.mp4" assets/video/hero.mp4          720 28
enc "$RAW/30391331.mp4" assets/video/showcase.mp4      720 28 -ss 2 -t 10
enc "$RAW/16818471.mp4" assets/video/hover-ppf.mp4     540 30
enc "$RAW/6159287.mp4"  assets/video/hover-wrap.mp4    540 30 -ss 0.5 -t 7
enc "$RAW/6159290.mp4"  assets/video/hover-ceramic.mp4 540 30 -ss 4 -t 7

# scroll-scrub sequence: 20s at 10fps = 200 frames, 1280w
"$FF" -y -v error -ss 0.5 -t 20 -i "$RAW/8470710.mp4" \
  -vf "fps=10,scale=1280:-2" -q:v 6 assets/frames/peel/finish_%04d.jpg

"$FF" -y -v error -ss 1  -i "$RAW/33374863.mp4" -frames:v 1 -vf scale=1280:-2 -q:v 4 assets/img/poster-hero.jpg
"$FF" -y -v error -ss 3  -i "$RAW/30391331.mp4" -frames:v 1 -vf scale=1280:-2 -q:v 4 assets/img/poster-showcase.jpg
"$FF" -y -v error -ss 18 -i "$RAW/8470710.mp4"  -frames:v 1 -vf scale=1280:-2 -q:v 4 assets/img/poster-finish.jpg

rm -rf "$RAW"
du -sh assets
