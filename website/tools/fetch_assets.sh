#!/usr/bin/env bash
# Regenerates website/assets from Pexels + Pixabay sources. Requires ffmpeg and curl.
# Usage: ./tools/fetch_assets.sh  (run from website/ root)
set -euo pipefail

RAW="$(mktemp -d)"
FF="${FFMPEG:-ffmpeg}"

# Pexels ids: hero corvette, showcase neon-gloss, hovers (water/roof/buffing)
for id in 33374863 8470710 16818471 6159287 6159290; do
  curl -sL "https://www.pexels.com/download/video/${id}/" -o "$RAW/${id}.mp4"
done
# Pixabay: tunnel drift animation (scrub centerpiece)
curl -sL "https://cdn.pixabay.com/video/2025/05/25/281584_large.mp4" -o "$RAW/281584.mp4"

mkdir -p assets/video assets/frames/peel assets/img

enc() { # enc <in> <out> <height> <crf> [extra input args...]
  local in="$1" out="$2" h="$3" crf="$4"; shift 4
  "$FF" -y -v error "$@" -i "$in" -an -vf "scale=-2:${h},fps=24" \
    -c:v libx264 -crf "$crf" -preset slow -pix_fmt yuv420p \
    -movflags +faststart "$out"
}

enc "$RAW/33374863.mp4" assets/video/hero.mp4          720 28
enc "$RAW/8470710.mp4"  assets/video/showcase.mp4      720 28 -ss 0.5 -t 9
enc "$RAW/16818471.mp4" assets/video/hover-ppf.mp4     540 30
enc "$RAW/6159287.mp4"  assets/video/hover-wrap.mp4    540 30 -ss 0.5 -t 7
enc "$RAW/6159290.mp4"  assets/video/hover-ceramic.mp4 540 30 -ss 4 -t 7

# scroll-scrub sequence: tunnel drift animation, 18.3s at 11fps ≈ 200 frames
"$FF" -y -v error -ss 0.2 -t 18.3 -i "$RAW/281584.mp4" \
  -vf "fps=11,scale=1280:-2" -q:v 6 assets/frames/peel/finish_%04d.jpg
rm -f assets/frames/peel/finish_0201.jpg

"$FF" -y -v error -ss 1  -i "$RAW/33374863.mp4" -frames:v 1 -vf scale=1280:-2 -q:v 4 assets/img/poster-hero.jpg
"$FF" -y -v error -ss 18 -i "$RAW/8470710.mp4"  -frames:v 1 -vf scale=1280:-2 -q:v 4 assets/img/poster-showcase.jpg
"$FF" -y -v error -ss 10 -i "$RAW/281584.mp4"  -frames:v 1 -vf scale=1280:-2 -q:v 4 assets/img/poster-finish.jpg

rm -rf "$RAW"
du -sh assets
