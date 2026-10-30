#!/usr/bin/env bash
# T07 acceptance: N6 unit tests, then fixture storyboards must match voiceover duration.
# No API key and no object store. HILATV_LIVE is forced off so the run stays on mocks.
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

# N6 does not need Postgres or MinIO. A configured-but-down MinIO would make mock TTS upload.
export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t07-$$.sqlite"
export HILATV_LIVE=0
export S3_ENDPOINT=
export S3_ACCESS_KEY=
export S3_SECRET_KEY=
export S3_BUCKET=
export MINIO_ENDPOINT=
export MINIO_ROOT_USER=
export MINIO_ROOT_PASSWORD=
export MINIO_BUCKET=

echo "== pytest n06_voiceover =="
"$PYTHON" -m pytest workers/nodes/n06_voiceover/tests gateway/tests/test_asr.py gateway/tests/test_media_bytes.py -q

echo "== fixture voiceover alignment =="
"$PYTHON" -m workers.nodes.n06_voiceover.accept
