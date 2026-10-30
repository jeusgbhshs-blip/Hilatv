#!/usr/bin/env bash
# T09 acceptance: N13 subtitles, N14 packaging, N15 FFmpeg compose.
# No API key. Plates, voice, and overlays are local.
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

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg and ffprobe are required for T09" >&2
  exit 1
fi

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t09-$$.sqlite"
export HILATV_LIVE=0
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=

echo "== pytest n13 n14 n15 =="
"$PYTHON" -m pytest \
  workers/nodes/n13_subtitle/tests \
  workers/nodes/n14_packaging/tests \
  workers/nodes/n15_compose/tests \
  -q

echo "== fixture compose =="
"$PYTHON" -m workers.nodes.n15_compose.accept
