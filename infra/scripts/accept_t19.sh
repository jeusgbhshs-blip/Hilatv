#!/usr/bin/env bash
# T19 acceptance: expert canvas, candidate view, and a manual re-run.
# Mock only. HILATV_LIVE stays off. No API key and no spend.
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
export PYTHON

API_PORT="${HILATV_ACCEPT_API_PORT:-8766}"
WEB_PORT="${HILATV_ACCEPT_WEB_PORT:-3457}"
API_ORIGIN="http://127.0.0.1:${API_PORT}"
WEB_ORIGIN="http://127.0.0.1:${WEB_PORT}"
PROJECT_DIR="${TMPDIR:-/tmp}/hilatv-t19-projects-$$"

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t19-$$.sqlite"
export HILATV_LIVE=0
export HILATV_TEMPORAL_MODE=embedded
export HILATV_TEMPORAL_CLOCK=local
export HILATV_PROJECT_DIR="${PROJECT_DIR}"
export HILATV_RENDER_WIDTH=320
export HILATV_RENDER_HEIGHT=180
export HILATV_KEYFRAME_CANDIDATES=3
export HILATV_VIDEO_CANDIDATES=3
export HILATV_QA_PROJECT_RETRIES=12
export HILATV_WEB_ORIGINS="${WEB_ORIGIN},http://127.0.0.1:3000,http://localhost:3000"
export HILATV_API_ORIGIN="${API_ORIGIN}"
export NEXT_PUBLIC_API_BASE="${API_ORIGIN}"
export PLAYWRIGHT_BASE_URL="${WEB_ORIGIN}"
export HILATV_EXPERT_PROJECT="t19expert"
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=
export REDIS_URL=
export DATABASE_URL=
export PYTHONPATH="$ROOT:$ROOT/apps/api${PYTHONPATH:+:$PYTHONPATH}"
unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD || true

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg and ffprobe are required for T19" >&2
  exit 1
fi

echo "== pytest expert canvas =="
"$PYTHON" -m pytest \
  workers/qa/tests/test_budget_store.py \
  workers/expert/tests \
  -q --tb=short

echo "== measured film =="
export HILATV_SESSION_SECRET="${HILATV_SESSION_SECRET:-t19-accept-session}"
"$PYTHON" -m workers.expert.accept
HILATV_E2E_SESSION="$("$PYTHON" - <<'PY'
from workers.identity.session import open_session
from workers.workflow.store import update_snapshot
import os

ident = open_session()
update_snapshot(os.environ.get("HILATV_EXPERT_PROJECT", "t19expert"), enterprise_id=ident.enterprise_id)
print(ident.token, end="")
PY
)"
export HILATV_E2E_SESSION

cd "$ROOT/apps/web"
if [[ ! -d node_modules/@playwright/test || ! -d node_modules/@xyflow/react ]]; then
  npm ci
fi

echo "== web unit tests =="
npm run test:unit

echo "== playwright chromium =="
npx playwright install --with-deps chromium

echo "== build web =="
npm run build

echo "== e2e expert canvas, desktop 1440x900 and mobile 390x844 =="
npx playwright test e2e/expert-canvas.spec.ts
