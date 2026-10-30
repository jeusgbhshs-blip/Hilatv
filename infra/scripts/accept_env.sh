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
