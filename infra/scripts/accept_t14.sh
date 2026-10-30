#!/usr/bin/env bash
# T14 acceptance: fault injection. No API key. HILATV_LIVE stays off.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ -z "${ENV_FILE:-}" ]]; then
  if [[ -f "$ROOT/.env" ]]; then
    ENV_FILE="$ROOT/.env"
  else
    ENV_FILE="$ROOT/.env.example"
  fi
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t14-$$.sqlite"
export HILATV_LIVE=0
export HILATV_BUDGET_CNY=0
export HILATV_DAILY_BUDGET_CNY=0
export HILATV_TEMPORAL_MODE=embedded
export HILATV_TEMPORAL_CLOCK=local
export HILATV_PROJECT_DIR="${TMPDIR:-/tmp}/hilatv-t14-projects-$$"
export HILATV_RENDER_WIDTH=320
export HILATV_RENDER_HEIGHT=180
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=
unset HILATV_FAIL_VIDEO_SHOTS || true
export PYTHONPATH="$ROOT:$ROOT/apps/api${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg and ffprobe are required for T14" >&2
  exit 1
fi

echo "== pytest fallback levels =="
"$PYTHON" -m pytest workers/fallback/tests workers/nodes/n10_video/tests/test_node.py workers/workflow/tests/test_messages.py -q --tb=short

echo "== fault injection workflow =="
"$PYTHON" -m workers.fallback.accept
