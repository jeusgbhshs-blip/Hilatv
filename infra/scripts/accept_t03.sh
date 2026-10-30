#!/usr/bin/env bash
# T03 acceptance: gateway unit tests, then a generate_text call whose row is
# read back from the call log. Postgres and Redis are used when they are up.
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

echo "== pytest gateway/tests =="
"$PYTHON" -m pytest gateway/tests -q

if "$PYTHON" - <<'PY'
import os
import sys

from gateway.store import postgres_reachable

sys.exit(0 if postgres_reachable(os.getenv("DATABASE_URL", "")) else 1)
PY
then
  echo "== alembic upgrade head =="
  "$PYTHON" -m alembic upgrade head
elif [[ "${ACCEPT_T03_REQUIRE_POSTGRES:-0}" == "1" ]]; then
  echo "postgres required but not reachable" >&2
  exit 1
fi

echo "== generate_text + call log =="
"$PYTHON" -m gateway.accept_smoke
