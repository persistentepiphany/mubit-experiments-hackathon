#!/usr/bin/env bash
set -euo pipefail

# Fetches the three tools the demo uses into demo/.tools, at the commits the
# demo was made with, and installs what each one needs. Run once per machine.
#
#   video-demo  films the scenes with Playwright, cursor, zoom and Kokoro voice
#   ndemo       renders the short cut from a YAML playbook
#   recordly    supplies the wallpaper for the frame (frame.py draws the rest)

DEMO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLS="$DEMO/.tools"
mkdir -p "$TOOLS"

fetch() {
  local name="$1" repo="$2" commit="$3"
  if [ ! -d "$TOOLS/$name/.git" ]; then
    git clone --filter=blob:none "https://github.com/$repo.git" "$TOOLS/$name"
  fi
  git -C "$TOOLS/$name" fetch --quiet origin "$commit" 2>/dev/null || true
  git -C "$TOOLS/$name" checkout --quiet "$commit"
}

fetch video-demo nilbuild/video-demo 767bfb818880c9f38bb02873d3d67141a3e62250
fetch ndemo splitbrain/ndemo d60e17e84b524dc89e8145844a030c47f4b9537d
fetch recordly webadderallorg/recordly 109ca3a13c362e969d9add25d1f93406c36dba2a

# Both Playwright users are pinned to the same version so they share one
# Chromium build. Set DEMO_PLAYWRIGHT to match a browser already installed.
PW="${DEMO_PLAYWRIGHT:-1.63.0}"

(
  cd "$TOOLS/video-demo"
  # Holds each line for its real spoken length (so lines never overlap),
  # exports the voice module, and writes each clip's narration timeline.
  git checkout --quiet -- . && git apply "$DEMO/patches/video-demo.patch"
  sed -i.bak "s/\"@playwright\/test\": \"[^\"]*\"/\"@playwright\/test\": \"$PW\"/" package.json && rm -f package.json.bak
  rm -f package-lock.json
  npm install --no-audit --no-fund
  mkdir -p node_modules && ln -sfn .. node_modules/video-demo
  bash scripts/install-voice.sh
)

(
  cd "$TOOLS/ndemo"
  npm install --no-audit --no-fund
  npm install --no-audit --no-fund "playwright@$PW"
  npm run build
)

npx --yes "playwright@$PW" install chromium

# The workspace links back to the engine and to this repository.
node "$TOOLS/video-demo/scripts/scaffold.mjs" "$DEMO/.." --project "$DEMO/video" >/dev/null
printf '\nsetup: done. Next: demo/record.sh\n'
