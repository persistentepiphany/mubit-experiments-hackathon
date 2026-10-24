#!/usr/bin/env bash
set -euo pipefail

# Records both cuts into demo/out:
#   labloop-folio-demo.mp4   the ~2 minute narrated tour (video-demo + frame)
#   labloop-folio-ndemo.mp4  the 1 minute cut (ndemo)
#
# Run demo/setup.sh first. Set ONLY=tour or ONLY=ndemo to record one of them.

DEMO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$DEMO/.tools"
OUT="$DEMO/out"
mkdir -p "$OUT"
ONLY="${ONLY:-all}"

if [ "$ONLY" != ndemo ]; then
  # Folio is filmed at 1280x720 and captured at 1.25x, so the tour is 1600x900,
  # which frame.py places on a 1920x1080 wallpaper. One worker keeps the
  # capture frame rate up on a small machine.
  DEMO_VIDEO_SCALE="${DEMO_VIDEO_SCALE:-1.25}" DEMO_WORKERS="${DEMO_WORKERS:-1}" \
    "$TOOLS/video-demo/scripts/demo" --project "$DEMO/video"
  python3 "$DEMO/frame.py" "$DEMO/video/demo-out/light/full-tour.mp4" \
    "$TOOLS/recordly/public/wallpapers/farmvalley.jpg" "$OUT/labloop-folio-demo.mp4"
fi

if [ "$ONLY" != tour ]; then
  node "$DEMO/mock-server.mjs" 8765 &
  SERVER=$!
  trap 'kill $SERVER 2>/dev/null' EXIT
  sleep 1
  PLAYBOOK="$DEMO/ndemo/folio-tour/folio-tour.yaml"
  node "$DEMO/ndemo/voice.mjs" "$PLAYBOOK" "$TOOLS/ndemo" "$TOOLS/video-demo"
  # The narration is already voiced locally, so ndemo never calls OpenAI.
  RUN=()
  if [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null 2>&1; then RUN=(xvfb-run -a); fi
  ${RUN[@]+"${RUN[@]}"} "$TOOLS/ndemo/ndemo" render "$PLAYBOOK" \
    --output "$OUT/labloop-folio-ndemo.mp4"
fi
