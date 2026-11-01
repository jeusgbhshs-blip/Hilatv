#!/usr/bin/env bash
# T04 acceptance: mock image, video, and TTS samples are stored and decoded.
# Object storage is MinIO (or any S3-compatible endpoint in MINIO_* / S3_*).
# This acceptance always disables live providers and uses the mock samples.
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
