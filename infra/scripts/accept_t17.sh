#!/usr/bin/env bash
# T17 acceptance: 9:16, 16:9, and 1:1 keep the subject inside the frame.
# No API key. Reframe, dub, and subtitles use the mock gateway.
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

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg and ffprobe are required for T17" >&2
  exit 1
fi

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t17-$$.sqlite"
export HILATV_LIVE=0
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=

echo "== pytest n17 =="
"$PYTHON" -m pytest \
  workers/nodes/n17_deliver/tests \
  apps/api/tests/test_deliveries.py \
  -q

echo "== fixture delivery =="
"$PYTHON" -m workers.nodes.n17_deliver.accept
