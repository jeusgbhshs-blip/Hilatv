#!/usr/bin/env bash
# T05 acceptance: N1 unit tests, then 20 fixture inputs must yield a legal Brief.
# The shared acceptance environment always disables live providers.
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

# N1 does not need Postgres. Keep the call log off the app database.
export HILATV_GATEWAY_STORE=sqlite
export HILATV_SQLITE_PATH="${TMPDIR:-/tmp}/hilatv-t05-$$.sqlite"

echo "== pytest n01_brief =="
"$PYTHON" -m pytest workers/nodes/n01_brief/tests -q

echo "== 20 fixture briefs =="
"$PYTHON" -m workers.nodes.n01_brief.accept
