#!/usr/bin/env bash
# Shared docker compose entry so `make up` and accept-t01 use the same project.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ -z "${ENV_FILE:-}" ]]; then
  if [[ -f "$ROOT/.env" ]]; then
    ENV_FILE="$ROOT/.env"
  else
    ENV_FILE="$ROOT/.env.example"
  fi
fi

# Project directory stays the compose file directory (infra/) so relative
# volume paths match `docker compose -f infra/docker-compose.yml`.
exec docker compose \
  --project-name hilatv \
  --env-file "$ENV_FILE" \
  -f "$ROOT/infra/docker-compose.yml" \
  "$@"
