#!/usr/bin/env bash
# UI-01 acceptance: DESIGN.md reskin and time-based theme.
# 1. No hard-coded colours or arbitrary Tailwind values in components / app.
# 2. Web unit tests (theme clock, status copy), lint, next build.
# 3. Every Playwright spec, including e2e/ui01-design.spec.ts:
#    P1 / P3 / P5 / P6 x light / dark x 1440 / 375, stage stays dark in light theme.
# Mock backend. No API key and no spend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
source "$ROOT/infra/scripts/accept_env.sh"

echo "== no hard-coded colours or arbitrary values =="
if git grep -nE "#[0-9a-fA-F]{6}|text-\[|rounded-\[|bg-\[" -- apps/web/components apps/web/app ':!apps/web/app/globals.css'; then
  echo "hard-coded value found" >&2
  exit 1
fi
if git grep -nE "(^|[\" ])[a-z:-]+-\[[^]]+\]" -- apps/web/components apps/web/app ':!apps/web/app/globals.css'; then
  echo "arbitrary Tailwind value found" >&2
  exit 1
fi
echo "none"

cd "$ROOT/apps/web"
if [[ ! -d node_modules/@playwright/test ]]; then
  npm ci
fi
echo "== web lint =="
npm run lint

cd "$ROOT"
# accept_t11.sh runs web unit tests, installs Chromium, builds, and runs every Playwright spec.
bash "$ROOT/infra/scripts/accept_t11.sh"
