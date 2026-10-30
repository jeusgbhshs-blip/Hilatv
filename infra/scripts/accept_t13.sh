#!/usr/bin/env bash
# T13 acceptance: anchors and product composite. Mock only. No API key.
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
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t13-$$.sqlite"
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
unset DASHSCOPE_API_KEY GEMINI_API_KEY SEEDREAM_API_KEY ARK_API_KEY DEEPSEEK_API_KEY || true

echo "== pytest N7 anchors, local vision, regen budget =="
"$PYTHON" -m pytest \
  workers/nodes/n07_anchor/tests \
  gateway/tests/test_local_vision.py \
  workers/qa/tests/test_budget_store.py \
  -q

echo "== product composite, face cosine, matting edge =="
"$PYTHON" -m workers.nodes.n07_anchor.accept
