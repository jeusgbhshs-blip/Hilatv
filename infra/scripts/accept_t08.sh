#!/usr/bin/env bash
# T08 acceptance: N8 keyframes and N10 image-to-video.
# No API key is required. HILATV_LIVE is forced off; the script uses the mock adapter.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/infra/scripts/accept_env.sh"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

# Keep gateway logs off Postgres. The accept module builds its own mock gateway.
export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t08-$$.sqlite"
export HILATV_LIVE=0

echo "== pytest n08_keyframe n10_video =="
"$PYTHON" -m pytest workers/nodes/n08_keyframe/tests workers/nodes/n10_video/tests -q

echo "== storyboard keyframes and trimmed clips =="
"$PYTHON" -m workers.nodes.n08_keyframe.accept
