#!/usr/bin/env bash
set -euo pipefail

# Records both cuts into demo/out:
#   labloop-mubit-demo.mp4    the narrated tour (video-demo scenes, composed)
#   labloop-mubit-ndemo.mp4   the one-minute cut (ndemo)
#
# Run demo/setup.sh first. Set ONLY=tour or ONLY=ndemo to record one of them.

DEMO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$DEMO/.tools"
OUT="$DEMO/out"
mkdir -p "$OUT"
ONLY="${ONLY:-all}"

if [ "$ONLY" != ndemo ]; then
  # Every line is voiced first, so each scene holds a line for its real length.
  node "$DEMO/video/prevoice.mjs"
  # Explainers are filmed full frame at 1920x1080; website scenes at 1600x900,
  # which compose.py places in a frame on a wallpaper. One worker keeps the
  # capture frame rate up on a small machine.
  DEMO_TOUR=0 DEMO_WORKERS=1 DEMO_VIDEO_SCALE=1.5 \
    "$TOOLS/video-demo/scripts/demo" --project "$DEMO/video" --grep "viz-"
  DEMO_TOUR=0 DEMO_WORKERS=1 DEMO_VIDEO_SCALE=1.25 DEMO_BUILD=0 \
    "$TOOLS/video-demo/scripts/demo" --project "$DEMO/video" --grep "task|run1|lesson|run2|reuse"
  python3 "$DEMO/compose.py" "$DEMO/video/demo-out/light" \
    "$TOOLS/recordly/public/wallpapers/farmvalley.jpg" "$OUT/labloop-mubit-demo.mp4"
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
    --output "$OUT/labloop-mubit-ndemo.mp4"
fi
