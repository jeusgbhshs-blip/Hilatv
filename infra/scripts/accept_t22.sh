#!/usr/bin/env bash
# T22 acceptance: N16 final review. Planted flaws, logo/CTA, mock judge and ASR.
# No API key. HILATV_LIVE stays off.
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
  echo "ffmpeg and ffprobe are required for T22" >&2
  exit 1
fi

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t22-$$.sqlite"
export HILATV_PROJECT_DIR="${TMPDIR:-/tmp}/hilatv-t22-projects-$$"
export HILATV_LIVE=0
export HILATV_BUDGET_CNY=0
export HILATV_DAILY_BUDGET_CNY=0
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=
unset DASHSCOPE_API_KEY GEMINI_API_KEY VOLC_ASR_API_KEY VOLC_ASR_APP_ID REDIS_URL || true
mkdir -p "$HILATV_PROJECT_DIR"

echo "== pytest n16 final review =="
"$PYTHON" -m pytest workers/nodes/n16_final_review/tests -q --tb=short

echo "== planted-flaw interception =="
"$PYTHON" -m workers.nodes.n16_final_review.accept
