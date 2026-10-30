#!/usr/bin/env bash
# T23 acceptance: storyboard cards, one-shot narration edit, skip-to-film.
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
export PYTHON

API_PORT="${HILATV_ACCEPT_API_PORT:-8771}"
WEB_PORT="${HILATV_ACCEPT_WEB_PORT:-3461}"
API_ORIGIN="http://127.0.0.1:${API_PORT}"
WEB_ORIGIN="http://127.0.0.1:${WEB_PORT}"

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t23-$$.sqlite"
export HILATV_LIVE=0
export HILATV_BUDGET_CNY=0
export HILATV_DAILY_BUDGET_CNY=0
export HILATV_TEMPORAL_MODE=embedded
export HILATV_TEMPORAL_CLOCK=local
export HILATV_PROJECT_DIR="${TMPDIR:-/tmp}/hilatv-t23-projects-$$"
export HILATV_RENDER_WIDTH=320
export HILATV_RENDER_HEIGHT=180
export HILATV_KEYFRAME_CANDIDATES=3
export HILATV_VIDEO_CANDIDATES=3
export HILATV_WEB_ORIGINS="${WEB_ORIGIN},http://127.0.0.1:3000,http://localhost:3000"
export HILATV_API_ORIGIN="${API_ORIGIN}"
export NEXT_PUBLIC_API_BASE="${API_ORIGIN}"
export PLAYWRIGHT_BASE_URL="${WEB_ORIGIN}"
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=
export PYTHONPATH="$ROOT:$ROOT/apps/api${PYTHONPATH:+:$PYTHONPATH}"
unset DEEPSEEK_API_KEY DASHSCOPE_API_KEY ARK_API_KEY GEMINI_API_KEY || true
unset SEEDREAM_API_KEY SEEDANCE_API_KEY MUREKA_API_KEY SUNO_API_KEY || true
unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD || true

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg and ffprobe are required for T23" >&2
  exit 1
fi

echo "== storyboard unit tests =="
"$PYTHON" -m pytest \
  workers/workflow/tests/test_storyboard.py \
  workers/workflow/tests/test_film.py \
  workers/workflow/tests/test_messages.py \
  -q --tb=short

echo "== skip, pause, hashes, prompts =="
"$PYTHON" -m workers.workflow.storyboard_accept

echo "== playwright cards =="
cd "$ROOT/apps/web"
if [[ ! -d node_modules/@playwright/test ]]; then
  npm ci
fi
npx playwright install --with-deps chromium
npm run build
npx playwright test e2e/storyboard.spec.ts
