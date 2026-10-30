#!/usr/bin/env bash
# T01 acceptance: every compose service is healthy, pgvector works,
# MinIO can create a bucket and round-trip an object, Temporal's default
# namespace is reachable.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/infra/scripts/accept_env.sh"

COMPOSE=(bash "$ROOT/infra/scripts/compose.sh")

echo "== docker compose ps =="
if ! "${COMPOSE[@]}" ps --format json | python3 -c '
import json
import sys

raw = sys.stdin.read().strip()
if not raw:
    print("no containers are running; run `make up` first")
    sys.exit(1)
if raw.startswith("["):
    rows = json.loads(raw)
else:
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]

required = {"postgres", "redis", "minio", "temporal", "temporal-ui"}
found = set()
bad = []
for row in rows:
    service = row.get("Service") or row.get("Name") or "?"
    health = row.get("Health") or ""
    state = row.get("State") or row.get("Status") or ""
    print(f"{service}\tstate={state}\thealth={health}")
    found.add(service)
    if health != "healthy":
        bad.append(f"{service} (health={health or 'missing'}, state={state})")

missing = sorted(required - found)
if missing:
    bad.append("missing services: " + ", ".join(missing))
if bad:
    print("UNHEALTHY")
    for item in bad:
        print(item)
    sys.exit(1)
print("all services healthy")
'; then
  echo "compose health check failed" >&2
  "${COMPOSE[@]}" ps || true
  "${COMPOSE[@]}" logs --tail 120 || true
  exit 1
fi

echo "== pgvector =="
"${COMPOSE[@]}" exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"
"${COMPOSE[@]}" exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
CREATE TABLE IF NOT EXISTS hilatv_accept_vec (id int PRIMARY KEY, embedding vector(3));
INSERT INTO hilatv_accept_vec (id, embedding) VALUES (1, '[1,2,3]')
ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding;
SQL
ext="$("${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "SELECT extname || ':' || extversion FROM pg_extension WHERE extname = 'vector';")"
ext="$(echo "$ext" | tr -d '[:space:]')"
if [[ -z "$ext" || "$ext" != vector:* ]]; then
  echo "pgvector extension missing (got '$ext')" >&2
  exit 1
fi
vec="$("${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
  "SELECT embedding::text FROM hilatv_accept_vec WHERE id = 1;")"
vec="$(echo "$vec" | tr -d '[:space:]')"
if [[ "$vec" != "[1,2,3]" ]]; then
  echo "pgvector round-trip failed (got '$vec')" >&2
  exit 1
fi
"${COMPOSE[@]}" exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "DROP TABLE hilatv_accept_vec;"
echo "pgvector ok ($ext)"

echo "== minio =="
"${COMPOSE[@]}" exec -T minio bash -lc "
set -euo pipefail
export PATH=\"/opt/bitnami/minio-client/bin:\$PATH\"
export MC_CONFIG_DIR=/tmp/mc
mkdir -p \"\$MC_CONFIG_DIR\"
mc alias set local http://127.0.0.1:9000 '${MINIO_ROOT_USER}' '${MINIO_ROOT_PASSWORD}' >/dev/null
mc mb --ignore-existing local/hilatv-accept >/dev/null
printf %s 'hilatv-accept-ok' | mc pipe local/hilatv-accept/probe.txt >/dev/null
got=\$(mc cat local/hilatv-accept/probe.txt | tr -d '[:space:]')
test \"\$got\" = 'hilatv-accept-ok'
echo minio upload/download ok
"

echo "== temporal =="
"${COMPOSE[@]}" exec -T temporal \
  temporal --address 127.0.0.1:7233 operator namespace describe --namespace default
echo "temporal namespace default ok"

echo "T01 accept: ok"
