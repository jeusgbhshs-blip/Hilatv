#!/usr/bin/env bash
# T15 acceptance: Brand Kit reuse and three concept cards. Mock only. No API key.
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
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t15-$$.sqlite"
export HILATV_BRAND_DIR="${TMPDIR:-/tmp}/hilatv-t15-brands-$$"
export HILATV_LIVE=0
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=
export DATABASE_URL=
export PYTHONPATH="$ROOT:$ROOT/apps/api${PYTHONPATH:+:$PYTHONPATH}"

echo "== pytest brand kit, N2, N3, API =="
"$PYTHON" -m pytest \
  workers/brand_kit/tests \
  workers/nodes/n03_concept/tests \
  apps/api/tests/test_brands.py \
  -q

echo "== reuse two projects and check concept cards =="
"$PYTHON" -m workers.nodes.n02_brand_kit.accept
