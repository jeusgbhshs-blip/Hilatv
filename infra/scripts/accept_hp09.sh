#!/usr/bin/env bash
# Complete Python regression gate, including draft concurrency and real media.
# Vendor requests stay disabled; generated test bytes and fake billing receipts
# exercise the real persistence, decoding, mixing and composition paths.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source "$ROOT/infra/scripts/accept_env.sh"

# Infrastructure roundtrips have their separate required-Postgres CI job.
# The default complete suite must not write mock media to a running MinIO.
export REDIS_URL= MINIO_ENDPOINT= MINIO_ROOT_USER= MINIO_ROOT_PASSWORD= MINIO_BUCKET=
if [[ "${HILATV_REQUIRE_DB:-0}" != "1" ]]; then
  export DATABASE_URL=
fi

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

for dependency in ffmpeg ffprobe tesseract; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    echo "$dependency is required for the complete regression gate" >&2
    exit 1
  fi
done
if ! tesseract --list-langs 2>/dev/null | awk '$0 == "chi_sim" { found = 1 } END { exit !found }'; then
  echo "tesseract chi_sim language data is required; OCR tests must not be skipped" >&2
  exit 1
fi

# Keep the complete default collection visible; no hand-picked subset can
# silently omit a node suite. Test fixtures select fake providers individually.
echo "HP09 complete regressions; artifacts: $HILATV_ACCEPT_WORK_DIR"
"$PYTHON" -m pytest -o addopts="" -q --tb=short \
  --basetemp="$HILATV_ACCEPT_WORK_DIR/pytest" \
  --junitxml="$HILATV_ACCEPT_WORK_DIR/results.xml"
