#!/usr/bin/env bash
# T12 acceptance: planted bad frames, interception rate, no live spend.
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
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t12-$$.sqlite"
export HILATV_LIVE=0
export HILATV_BUDGET_CNY=0
export HILATV_DAILY_BUDGET_CNY=0
unset DASHSCOPE_API_KEY GEMINI_API_KEY || true

echo "== pytest N9 N11 qa =="
"$PYTHON" -m pytest \
  workers/qa/tests \
  workers/nodes/n09_keyframe_qa/tests \
  workers/nodes/n11_video_qa/tests \
  gateway/tests/test_judge_vision.py \
  -q

echo "== planted-defect interception report =="
"$PYTHON" -m workers.qa
