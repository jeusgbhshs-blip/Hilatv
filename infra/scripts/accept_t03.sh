#!/usr/bin/env bash
# T03 acceptance: gateway unit tests, then a generate_text call whose row is
# read back from the call log. Postgres and Redis are used when they are up.
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

echo "== pytest gateway/tests =="
"$PYTHON" -m pytest gateway/tests -q

echo "== generate_text + call log =="
"$PYTHON" -m gateway.accept_smoke
