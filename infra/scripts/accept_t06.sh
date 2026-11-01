#!/usr/bin/env bash
# T06 acceptance: N4/N5 unit tests, then fixture briefs must meet the duration and provenance rules.
# No API key is required. The shared acceptance environment forces live off.
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

# N4/N5 do not need Postgres. Keep the call log off the app database.
export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t06-$$.sqlite"
export HILATV_LIVE=0

echo "== pytest n04_script n05_storyboard =="
"$PYTHON" -m pytest workers/nodes/n04_script/tests workers/nodes/n05_storyboard/tests -q

echo "== fixture scripts and storyboards =="
"$PYTHON" -m workers.nodes.n04_script.accept
