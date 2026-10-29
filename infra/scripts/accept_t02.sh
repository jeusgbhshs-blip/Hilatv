#!/usr/bin/env bash
# T02 acceptance: schema unit tests plus Alembic upgrade/downgrade on Postgres.
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

export HILATV_REQUIRE_DB=1

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  PY=python3
fi

echo "== postgres =="
if ! "$PY" - <<'PY'
import os
import socket
from urllib.parse import urlparse

url = urlparse(os.environ["DATABASE_URL"])
host = url.hostname or "localhost"
port = url.port or 5432
with socket.create_connection((host, port), 3):
    pass
print(f"reachable {host}:{port}")
PY
then
  echo "Postgres is not reachable; starting the compose postgres service"
  ENV_FILE="$ENV_FILE" bash "$ROOT/infra/scripts/compose.sh" up -d --wait --wait-timeout 180 postgres
fi

echo "== alembic upgrade head =="
"$PY" -m alembic upgrade head
echo "== alembic downgrade base =="
"$PY" -m alembic downgrade base
echo "== alembic upgrade head =="
"$PY" -m alembic upgrade head
echo "== alembic heads =="
"$PY" -m alembic heads

echo "== schema tests =="
"$PY" -m pytest workers/schemas/tests -q \
  --cov=workers.schemas \
  --cov-report=term-missing \
  --cov-fail-under=90
