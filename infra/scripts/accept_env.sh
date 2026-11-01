# Source only .env.example. Never a developer .env.
# Then drop vendor secrets so an acceptance run cannot call a live API.
if [[ -z "${ROOT:-}" ]]; then
  echo "accept_env.sh requires ROOT" >&2
  return 1 2>/dev/null || exit 1
fi
set -a
# shellcheck disable=SC1091
source "$ROOT/.env.example"
set +a
while IFS= read -r _accept_name; do
  case "$_accept_name" in
    *API_KEY*|*SECRET*) unset "$_accept_name" ;;
  esac
done < <(compgen -e)
unset _accept_name

# Inherited production storage overrides must not receive mock sample writes.
unset S3_ENDPOINT S3_ACCESS_KEY S3_SECRET_KEY S3_BUCKET S3_REGION S3_ADDRESSING
unset HILATV_ROUTES_PATH HILATV_PRICING_PATH HILATV_SESSION_REVOCATION_PATH
unset PYTEST_ADDOPTS
export ENV_FILE="$ROOT/.env.example"
export HILATV_LIVE=0 HILATV_BUDGET_CNY=0 HILATV_DAILY_BUDGET_CNY=0
export HILATV_CANVAS_DB=0
export HILATV_GATEWAY_STORE=sqlite
export PYTHONPATH="$ROOT:$ROOT/apps/api${PYTHONPATH:+:$PYTHONPATH}"

# Each acceptance owns fresh files. Nothing falls back to a running user's
# project directory, application database log, or tracked progress document.
HILATV_ACCEPT_WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hilatv-accept.XXXXXX")"
export HILATV_ACCEPT_WORK_DIR
export HILATV_PROJECT_DIR="$HILATV_ACCEPT_WORK_DIR/projects"
export HILATV_BRAND_DIR="$HILATV_ACCEPT_WORK_DIR/brands"
export HILATV_SQLITE_PATH="$HILATV_ACCEPT_WORK_DIR/gateway.sqlite"
export HILATV_PROGRESS_PATH="$HILATV_ACCEPT_WORK_DIR/progress.md"
