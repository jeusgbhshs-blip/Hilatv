#!/usr/bin/env bash
# T21 acceptance: N12 music, beat alignment, ducking, loudness, licenses.
# No API key. HILATV_LIVE stays off. Test tones are synthesized in-repo.
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
  echo "ffmpeg and ffprobe are required for T21" >&2
  exit 1
fi

export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t21-$$.sqlite"
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
unset MUREKA_API_KEY SUNO_API_KEY REDIS_URL || true

echo "== pytest n12 =="
"$PYTHON" -m pytest workers/nodes/n12_music/tests workers/nodes/n15_compose/tests/test_audio_track.py -q --tb=short

echo "== mix measurements =="
"$PYTHON" -m workers.nodes.n12_music.accept
