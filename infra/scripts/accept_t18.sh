#!/usr/bin/env bash
# T18 acceptance: 60 briefs, mock mode, score table.
# No API key. HILATV_LIVE stays off. Storyboard depth does not encode MP4s.
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

OUT="${TMPDIR:-/tmp}/hilatv-t18-$$"
mkdir -p "$OUT"

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${OUT}/gateway.sqlite"
export HILATV_LIVE=0
export HILATV_BUDGET_CNY=0
export HILATV_DAILY_BUDGET_CNY=0
export HILATV_PROGRESS_PATH="${OUT}/progress.md"
export HILATV_EVAL_MODE=mock
export REDIS_URL=
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

echo "== pytest eval =="
"$PYTHON" -m pytest eval/tests -q

echo "== 60 briefs, mock score table =="
"$PYTHON" eval/run_eval.py --mode mock --out "$OUT/report" --strict

echo "accept-t18 ok: $OUT/report"
