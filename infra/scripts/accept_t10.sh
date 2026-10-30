#!/usr/bin/env bash
# T10 acceptance: one sentence to a playable MP4 through the Temporal film workflow.
# No API key. HILATV_LIVE stays off. The embedded dev server does not need Compose.
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

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t10-$$.sqlite"
export HILATV_LIVE=0
export HILATV_TEMPORAL_MODE=embedded
export HILATV_TEMPORAL_CLOCK=local
export HILATV_PROJECT_DIR="${TMPDIR:-/tmp}/hilatv-t10-projects-$$"
export HILATV_RENDER_WIDTH=320
export HILATV_RENDER_HEIGHT=180
export HILATV_KEYFRAME_CANDIDATES=3
export HILATV_VIDEO_CANDIDATES=3
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=
export PYTHONPATH="$ROOT:$ROOT/apps/api${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg and ffprobe are required for T10" >&2
  exit 1
fi

echo "== pytest workflow =="
"$PYTHON" -m pytest workers/workflow/tests -q

echo "== one sentence to mp4 =="
"$PYTHON" -m workers.workflow.accept
