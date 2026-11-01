# Gateway money admission and settlement

All existing entry points use the same guard. A paid candidate needs a persistent
ledger, an enforceable cost upper bound, and room in both the total and Shanghai-day
budget. Cache hits and mock/local adapters cost zero and do not reserve money.

## Price bounds are opt-in

Bundled `pricing.yaml` values are assumed estimates, not verified billing limits.
They therefore **do not admit paid calls** by default, even when live and positive
budgets are configured. The gateway returns a schema-valid mock with a logged
`unbounded_cost` reason. A real moderator stays unreviewed/fail-closed instead of
reporting mock moderation as a live safety pass.

An operator may add a `cost_bounds` entry to their reviewed pricing configuration
only after verifying the model tariff, units, supported dimensions, and provider
request limit. Example configuration shape (not an approval of any vendor price):

```yaml
models:
  reviewed-text-model:
    unit: token
    input_per_million: "2"
    output_per_million: "8"
cost_bounds:
  reviewed-text-model:
    verified: true
    input_tokenizer: utf8_bytes
    output_parameter: max_tokens
```

The text adapter explicitly sends `max_tokens` (caller value or configured default).
It bounds text input using the serialized actual request's ASCII-escaped byte count;
this requires a verified UTF-8 byte-tokenizer bound. Vision-token billing has no
approved upper-bound implementation and falls back to mock. Token counts estimated
from average character density cannot admit paid calls.

Image bounds additionally list `image_sizes` (for example `["1K"]`) for their fixed
per-image tariff. Quantity participates in the bound; Seedream currently only admits
its supported single-image request. Video bounds list `video_resolutions`, with cost
based on the duration actually placed in the submit body. Unsupported resolutions or
unbounded dimensions fall back to mock. TTS uses text character count. ASR currently
requires locally decodable WAV bytes to establish its duration bound; unsupported
input formats fall back to mock. Unknown models never inherit a default hard bound.

The six-decimal reservation amount rounds **up**, so the guard never reserves less
than the verified bound at ledger precision. Every fallback is separately re-priced
and admitted; the primary's cheap estimate is not reused for an expensive fallback.

## Durable outstanding obligations

SQLite uses `BEGIN IMMEDIATE`; Postgres uses a common transaction-level advisory
lock. Admission adds outstanding reservations to already logged live cost, checks
both caps, and inserts the hold atomically. No transaction lock spans provider I/O.
Memory-only SQLite cannot admit a paid call. Multi-host deployments must share the
same Postgres ledger, not independent local SQLite files.

An unfinished call may finish after midnight, so its hold remains counted against
the current day's available room until it has an outcome. Actual settled cost is
recorded on the Shanghai completion day. Normal settled daily totals reset by day;
outstanding/unknown obligations do not disappear at midnight or restart.
Admission samples its Shanghai day inside the database lock: a call queued before
midnight cannot use yesterday's totals after waiting for that lock into today.

Provider completion is distinct from usable application output. Known usage/cost is
settled even when JSON/schema validation, media download or object persistence
fails. Built-in text/image/video/TTS/ASR adapters preserve available receipts across
postprocessing failures. A timeout or missing receipt is not proof of zero charge:
it leaves an `uncertain` hold and a `billing_unknown` log, requiring reconciliation.
No expiry silently frees that obligation. A crashed process also leaves its hold.
A later verified receipt can be settled once using `SqlStore.settle_budget`; identical
replays are no-ops, conflicting amounts are rejected. Reservation + charge log commit
atomically, with a unique receipt ID. There is no new public reconciliation endpoint
in this change; provider-specific invoice/task reconciliation is follow-up work.

If a provider charges above its verified bound, retain the real reported fee, emit an
alert, mark `settled_overrun`, and disallow that provider/model/price configuration
fingerprint until the tariff/bound is reviewed. Software cannot undo already incurred
external charges or promise a provider honors a contract; it must stop trusting a
violated bound rather than mask the overrun or keep admitting the same unsafe price.

## Rollout and rollback

Apply Alembic `hp03_budget_0004` before the gateway version using it. Pause paid
admission (`HILATV_LIVE=0`) for the upgrade, stop older writers, and do not run a mixed
fleet where old gateways ignore reservations. Existing call logs remain part of the
budget, so migration does not reset spent money. This migration only adds the
reservation table/index; it does not rewrite invoices or existing canvas records.
Downgrade refuses to erase reserved/uncertain obligations. Prefer application rollback
with the additive schema retained; reconcile obligations before any schema removal.

Budget fallback is not cached, so corrected caps/bounds can take effect. Logged
provider/model, reason, reservation ID and context preserve provenance without
changing business output schemas. Recursive log-only redaction replaces data-URL
bytes and signed URL credentials with hashes; actual adapter requests, cache keys,
cached output and returned media URIs are unchanged.

## Local verification (fake providers only)

```sh
PYTHONPATH="$PWD:$PWD/apps/api" HILATV_LIVE=0 HILATV_PROGRESS_PATH=/tmp/hp03-progress.md \
  /Users/ci/Hilatv/.venv/bin/python -m pytest gateway/tests/test_budget_atomic.py -q
```

The tests use scripted adapters or `httpx.MockTransport`, never vendor network calls.
Postgres migration SQL compiles offline; a shared live Postgres instance is still
needed for deployment-level advisory-lock/recovery acceptance.
