#!/usr/bin/env bash
# Fetch a static ffmpeg build into ~/.promptcut/ffmpeg (Linux x86_64/arm64).
# macOS/Windows users: install ffmpeg with brew/winget instead.
set -euo pipefail

DEST="${HOME}/.promptcut/ffmpeg"
mkdir -p "$DEST"

if command -v ffmpeg >/dev/null 2>&1; then
  echo "system ffmpeg found: $(command -v ffmpeg) — nothing to do"
  exit 0
fi
if ls "$DEST"/ffmpeg-*-static/ffmpeg >/dev/null 2>&1; then
  echo "static ffmpeg already present in $DEST"
  exit 0
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  PKG="ffmpeg-release-amd64-static.tar.xz" ;;
  aarch64|arm64) PKG="ffmpeg-release-arm64-static.tar.xz" ;;
  *) echo "unsupported arch: $ARCH — install ffmpeg manually"; exit 1 ;;
esac

echo "downloading johnvansickle static ffmpeg ($PKG)…"
curl -fL "https://johnvansickle.com/ffmpeg/releases/$PKG" -o "$DEST/$PKG"
tar xf "$DEST/$PKG" -C "$DEST"
rm "$DEST/$PKG"
"$DEST"/ffmpeg-*-static/ffmpeg -version | head -1
echo "installed into $DEST"
