#!/usr/bin/env bash
# T04 acceptance: mock image, video, and TTS samples are stored and decoded.
# Object storage is MinIO (or any S3-compatible endpoint in MINIO_* / S3_*).
# HILATV_LIVE=1 with a budget and a vendor key adds one live sample per modality.
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

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "ffmpeg and ffprobe are required to encode and decode the T04 samples" >&2
  exit 1
fi

echo "== pytest media adapters =="
"$PYTHON" -m pytest \
  gateway/tests/test_polling.py \
  gateway/tests/test_media_bytes.py \
  gateway/tests/test_media_adapters.py \
  gateway/tests/test_object_store.py \
  gateway/tests/test_pricing.py \
  -q

if "$PYTHON" - <<'PY'
import os
import sys

from gateway.store import postgres_reachable

sys.exit(0 if postgres_reachable(os.getenv("DATABASE_URL", "")) else 1)
PY
then
  echo "== alembic upgrade head =="
  "$PYTHON" -m alembic upgrade head
elif [[ "${ACCEPT_T04_REQUIRE_POSTGRES:-0}" == "1" ]]; then
  echo "postgres required but not reachable" >&2
  exit 1
fi

echo "== image, video, tts samples =="
"$PYTHON" -m gateway.accept_media
