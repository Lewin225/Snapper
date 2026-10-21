#!/bin/bash
# Builds tests/media/tears_of_steel.mp4, the default test video: "Tears of Steel" (Blender Foundation, CC BY 3.0) at 480p
# with a WhisperX subtitle track (tears_of_steel.srt, generated once) embedded as mov_text. The 122 MB video is downloaded
# on demand and checked against a SHA-256, so it is not stored in the repository. Needs curl and ffmpeg.
set -euo pipefail
HERE="$(dirname "$(readlink -f "$0")")/media"
OUT="$HERE/tears_of_steel.mp4"
URL="https://video.blender.org/object-storage/web_videos/8533ea43-4271-4a57-9694-e9d0b35e1aa1-480.mp4"
SHA256="f450e73d44b6991169127f2e2a76a08aa4910eba834c243e0ab7f0b01e8a7264"

[ -s "$OUT" ] && { echo "$OUT is already there."; exit 0; }
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
echo "Downloading Tears of Steel (480p, 122 MB)…"
curl -fL --retry 3 -o "$TMP/original.mp4" "$URL"
echo "$SHA256  $TMP/original.mp4" | sha256sum -c - || { echo "The download does not match the expected file; not using it." >&2; exit 1; }
ffmpeg -v error -i "$TMP/original.mp4" -i "$HERE/tears_of_steel.srt" -map 0:v -map 0:a -map 1:0 -c copy -c:s mov_text \
    -metadata:s:s:0 language=eng -metadata:s:s:0 title="WhisperX (test fixture)" -movflags +faststart "$TMP/tears_of_steel.mp4"
mv "$TMP/tears_of_steel.mp4" "$OUT"
echo "Wrote $OUT"
