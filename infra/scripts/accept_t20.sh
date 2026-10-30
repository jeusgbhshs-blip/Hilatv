#!/usr/bin/env bash
# T20 acceptance: AI label, content review, consent, and the rights note.
# No API key. Content safety uses the mock gateway. OCR uses tesseract.
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
  echo "ffmpeg and ffprobe are required for T20" >&2
  exit 1
fi
if ! command -v tesseract >/dev/null 2>&1; then
  echo "tesseract (chi_sim) is required for T20" >&2
  exit 1
fi

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t20-$$.sqlite"
export HILATV_LIVE=0
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=

echo "== pytest t20 =="
"$PYTHON" -m pytest \
  workers/nodes/n16_review/tests \
  workers/compliance/tests \
  workers/schemas/tests/test_licensing.py \
  workers/nodes/n14_packaging/tests/test_node.py \
  workers/nodes/n17_deliver/tests/test_node.py \
  -q --tb=short

echo "== export ocr and metadata =="
"$PYTHON" -m workers.nodes.n16_review.accept
