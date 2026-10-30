#!/usr/bin/env bash
# T16 acceptance: hand-written edit set, logo calls, hashes, rollback.
# No API key. HILATV_LIVE stays off. Mock adapters only.
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
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t16-$$.sqlite"
export HILATV_LIVE=0
export HILATV_BUDGET_CNY=0
export HILATV_DAILY_BUDGET_CNY=0
export HILATV_PROJECT_DIR="${TMPDIR:-/tmp}/hilatv-t16-projects-$$"
export HILATV_RENDER_WIDTH=160
export HILATV_RENDER_HEIGHT=90
export HILATV_SHOT_WORKERS=2
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
unset DEEPSEEK_API_KEY DASHSCOPE_API_KEY ARK_API_KEY GEMINI_API_KEY SEEDREAM_API_KEY SEEDANCE_API_KEY || true

"$PYTHON" -m workers.nodes.n18_revision.accept
