"""Real money invariants with fake providers; no network or actual vendor spend."""

from __future__ import annotations

import base64
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import BaseModel

from gateway.adapters.seedream import SeedreamAdapter
from gateway.budget import BudgetGuard
from gateway.clock import FrozenClock
from gateway.errors import GatewayError, StorageError
from gateway.models import AdapterResult
from gateway.store import SqlStore
from gateway.tests.conftest import build_gateway
from gateway.tests.test_budget import ROUTES, FlatPricing, Priced


class Brief(BaseModel):
    goal: str


def _reserve_worker(path, barrier, results, total, daily):
    store = SqlStore.sqlite(path)
    barrier.wait(timeout=10)
    import uuid

    decision = store.reserve_budget(
        reservation_id=str(uuid.uuid4()),
        day="2026-11-01",
        created_at="2026-11-01T12:00:00+08:00",
        estimate=Decimal("0.04"),
        total_cap=Decimal(total),
        daily_cap=Decimal(daily),
        context={},
    )
    results.put(decision["allowed"])
    store.close()


@pytest.mark.parametrize("total,daily", [("0.05", "10"), ("10", "0.05")])
def test_multiple_processes_reserve_both_caps_atomically(tmp_path, total, daily):
    path = tmp_path / "shared.sqlite"
    SqlStore.sqlite(path).close()
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    results = context.Queue()
    processes = [
        context.Process(target=_reserve_worker, args=(str(path), barrier, results, total, daily))
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=15)
        if process.is_alive():
            process.terminate()
            process.join()
        assert process.exitcode == 0
    assert sum(results.get(timeout=2) for _ in processes) == 1
    store = SqlStore.sqlite(path)
    assert store.budget_totals("2026-11-01")["reserved"] == Decimal("0.04")
    store.close()


def test_lock_wait_crossing_midnight_uses_the_admission_day_not_the_queued_day(tmp_path):
    path = tmp_path / "midnight.sqlite"
    queued, writer = SqlStore.sqlite(path), SqlStore.sqlite(path)
    clock = FrozenClock(datetime.fromisoformat("2026-11-01T23:59:59+08:00"))
    waiting, release = threading.Event(), threading.Event()
    transaction = queued._budget_transaction

    @contextmanager
    def wait_for_writer():
        waiting.set()
        assert release.wait(timeout=5)
        with transaction():
            yield

    queued._budget_transaction = wait_for_writer
    guard = BudgetGuard(
        store=queued,
        limits_fn=lambda: (True, Decimal("10"), Decimal("0.05")),
        clock=clock,
        progress_path=None,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(guard.reserve, Decimal("0.04"))
        assert waiting.wait(timeout=3)
        clock.set(datetime.fromisoformat("2026-11-02T00:00:01+08:00"))
        writer.insert_log(
            {**_log_row("0.04"), "day": "2026-11-02", "created_at": clock.now().isoformat()}
        )
        release.set()
        decision = future.result(timeout=3)
    assert not decision.allowed and decision.reason == "daily"
    assert decision.daily_spent == Decimal("0.04") and queued.list_reservations() == []
    queued.close()
    writer.close()


def test_inflight_call_blocks_another_gateway_without_holding_network_lock(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class Blocking(Priced):
        def invoke(self, call):
            entered.set()
            assert release.wait(timeout=5)
            return super().invoke(call)

    adapter = Blocking("0.04")
    common = dict(
        routes=ROUTES,
        registry={"priced": adapter},
        pricing=FlatPricing("0.04"),
        limits=(True, Decimal("0.05"), Decimal("10")),
    )
    one, two = build_gateway(tmp_path, **common), build_gateway(tmp_path, **common)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(one.generate_text, "first")
        assert entered.wait(timeout=3)
        try:
            second = pool.submit(two.generate_text, "different").result(timeout=3)
            assert second["mock"] is True
        finally:
            release.set()
        assert first.result(timeout=3)["text"] == "live-1"
    assert adapter.calls == 1
    assert one.store.sum_cost() == Decimal("0.04")
    assert one.store.budget_totals(one.budget.today())["reserved"] == 0


def test_fallback_is_reestimated_and_cannot_use_cheaper_primary_reservation(tmp_path):
    routes = ROUTES.replace("fallbacks: []", "fallbacks: [{provider: expensive, model: costly}]")

    class Down(Priced):
        def invoke(self, call):
            self.calls += 1
            raise TimeoutError("provider outcome unknown")

    class Pricing(FlatPricing):
        def estimate(self, model, prompt, **kwargs):
            return Decimal("0.20") if model == "costly" else Decimal("0.01")

    primary, expensive = Down("0"), Priced("0.20")
    gateway = build_gateway(
        tmp_path,
        routes=routes,
        registry={"priced": primary, "expensive": expensive},
        pricing=Pricing("0.01"),
        limits=(True, Decimal("0.05"), Decimal("10")),
    )
    assert gateway.generate_text("fallback")["mock"] is True
    assert primary.calls == 1 and expensive.calls == 0
    logs = gateway.store.list_logs()
    assert logs[0]["fallback_reason"] == "billing_unknown"
    assert logs[-1]["fallback_reason"] == "budget_exceeded"
    assert logs[-1]["params"]["budget_reason"] == "total"
    assert gateway.store.list_reservations()[0]["state"] == "uncertain"


def test_paid_schema_failure_keeps_cost_and_blocks_unaffordable_fallback(tmp_path):
    routes = ROUTES.replace("fallbacks: []", "fallbacks: [{provider: other, model: other}]")

    class Invalid(Priced):
        def invoke(self, call):
            self.calls += 1
            return AdapterResult("priced", call.model, {"wrong": True}, Decimal("0.04"))

    primary, other = Invalid("0.04"), Priced("0.04")
    gateway = build_gateway(
        tmp_path,
        routes=routes,
        registry={"priced": primary, "other": other},
        pricing=FlatPricing("0.04"),
        limits=(True, Decimal("0.05"), Decimal("10")),
    )
    Brief.model_validate(gateway.generate_text("structured", schema=Brief))
    assert primary.calls == 1 and other.calls == 0
    logs = gateway.store.list_logs()
    assert logs[0]["status"] == "error" and Decimal(logs[0]["cost_cny"]) == Decimal("0.04")
    assert logs[-1]["provider"] == "mock" and Decimal(logs[-1]["cost_cny"]) == 0
    assert gateway.store.sum_cost() == Decimal("0.04")


def test_successful_image_provider_storage_failure_is_still_billed(tmp_path):
    class BrokenStore:
        def put(self, *args):
            raise StorageError("disk full after provider completion")

    payload = {"data": [{"b64_json": base64.b64encode(b"image").decode()}]}
    adapter = SeedreamAdapter(
        api_key="fake-not-a-secret",
        store=BrokenStore(),
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    routes = ROUTES.replace("task: llm", "task: image").replace(
        "provider: priced, model: deepseek-chat", "provider: seedream, model: seedream-4-0"
    )
    gateway = build_gateway(
        tmp_path,
        routes=routes,
        registry={"seedream": adapter},
        pricing=FlatPricing("0.20"),
        limits=(True, Decimal("0.20"), Decimal("1")),
    )
    with pytest.raises(GatewayError, match="all adapters failed"):
        gateway.generate_image("image")
    assert gateway.store.sum_cost() == Decimal("0.20")
    assert gateway.store.list_logs()[0]["status"] == "error"
    assert gateway.store.list_reservations()[0]["state"] == "settled"


def _log_row(cost="0.04"):
    return dict(
        created_at="2026-11-01T12:00:01+08:00",
        day="2026-11-01",
        task="llm",
        provider="fake",
        model="fake",
        params={},
        latency_ms=1,
        cost_cny=cost,
        status="ok",
        cache_hit=False,
        live=True,
    )


def test_settlement_is_once_across_independent_connections(tmp_path):
    path = tmp_path / "settle.sqlite"
    one, two = SqlStore.sqlite(path), SqlStore.sqlite(path)
    one.reserve_budget(
        reservation_id="receipt",
        day="2026-11-01",
        created_at="now",
        estimate=Decimal("0.04"),
        total_cap=Decimal("1"),
        daily_cap=Decimal("1"),
        context={},
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda s: s.settle_budget("receipt", _log_row()), [one, two]))
    assert sorted(results) == [False, True]
    assert len(one.list_logs()) == 1
    assert one.sum_cost() == Decimal("0.04")
    assert one.budget_totals("2026-11-01")["reserved"] == 0


def test_uncertain_reservation_survives_restart_and_midnight_until_reconciled(tmp_path):
    path = tmp_path / "pending.sqlite"
    one = SqlStore.sqlite(path)
    one.reserve_budget(
        reservation_id="pending",
        day="2026-10-31",
        created_at="yesterday",
        estimate=Decimal("0.04"),
        total_cap=Decimal("1"),
        daily_cap=Decimal("0.05"),
        context={},
    )
    one.hold_uncertain_budget("pending")
    one.close()
    two = SqlStore.sqlite(path)
    blocked = two.reserve_budget(
        reservation_id="next",
        day="2026-11-01",
        created_at="today",
        estimate=Decimal("0.04"),
        total_cap=Decimal("1"),
        daily_cap=Decimal("0.05"),
        context={},
    )
    assert not blocked["allowed"] and blocked["reason"] == "daily"
    # A reconciliation can record a verified zero receipt without double-charging later.
    assert two.settle_budget("pending", _log_row("0"))
    assert not two.settle_budget("pending", _log_row("0"))
    assert two.reserve_budget(
        reservation_id="after",
        day="2026-11-01",
        created_at="today",
        estimate=Decimal("0.04"),
        total_cap=Decimal("1"),
        daily_cap=Decimal("0.05"),
        context={},
    )["allowed"]


def test_cache_and_mock_do_not_create_or_charge_reservations(tmp_path):
    adapter = Priced("0.04")
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"priced": adapter},
        pricing=FlatPricing("0.04"),
        limits=(True, Decimal("1"), Decimal("1")),
    )
    gateway.generate_text("same", seed=3)
    gateway.generate_text("same", seed=3)
    assert adapter.calls == 1
    assert len(gateway.store.list_reservations()) == 1
    assert gateway.store.list_logs()[-1]["cost_cny"] == "0.000000"
    assert gateway.store.budget_totals(gateway.budget.today())["reserved"] == 0


def test_assumed_prices_cannot_admit_paid_calls_even_with_a_large_budget(tmp_path):
    from gateway.pricing import Pricing

    adapter = Priced("0.04")
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"priced": adapter},
        pricing=Pricing.load(),
        limits=(True, Decimal("100"), Decimal("100")),
    )
    assert gateway.generate_text("no verified maximum")["mock"] is True
    assert adapter.calls == 0
    assert gateway.store.list_logs()[-1]["fallback_reason"] == "unbounded_cost"
    assert gateway.store.list_reservations() == []


def test_reviewed_token_bound_is_enforced_in_actual_http_request(tmp_path):
    from gateway.adapters.openai_compat import OpenAICompatAdapter
    from gateway.pricing import Pricing

    requests = []

    def handler(request):
        import json

        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "bounded"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        )

    pricing = Pricing(
        {
            "default_output_tokens": 16,
            "models": {"bounded": {"input_per_million": "2", "output_per_million": "8"}},
            "cost_bounds": {
                "bounded": {
                    "verified": True,
                    "input_tokenizer": "utf8_bytes",
                    "output_parameter": "max_tokens",
                }
            },
        }
    )
    adapter = OpenAICompatAdapter(
        provider="priced",
        api_key="fake",
        base_url="https://fake.test",
        transport=httpx.MockTransport(handler),
    )
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES.replace("deepseek-chat", "bounded"),
        registry={"priced": adapter},
        pricing=pricing,
        limits=(True, Decimal("1"), Decimal("1")),
    )
    assert gateway.generate_text("a lot of 中文 input") == {"text": "bounded"}
    assert requests[0]["max_tokens"] == 16
    reservation = gateway.store.list_reservations()[0]
    assert Decimal(reservation["amount_cny"]) >= Decimal("0.000128")
    assert reservation["state"] == "settled"


def test_media_upper_bounds_include_quantity_size_duration_and_resolution():
    from gateway.pricing import Pricing

    pricing = Pricing(
        {
            "models": {
                "image": {"unit": "image", "per_image": "0.20"},
                "video": {"unit": "second", "per_second": "0.50"},
            },
            "cost_bounds": {
                "image": {"verified": True, "image_sizes": ["1K"]},
                "video": {"verified": True, "video_resolutions": ["720p"]},
            },
        }
    )
    assert pricing.upper_bound("image", "x", task="image", params={"n": 4}) == Decimal("0.80")
    assert pricing.upper_bound("image", "x", task="image", params={"size": "4K"}) is None
    assert pricing.upper_bound(
        "video", "x", task="video", params={"duration_s": 10, "resolution": "720p"}
    ) == Decimal("5")
    assert (
        pricing.upper_bound(
            "video", "x", task="video", params={"duration_s": 10, "resolution": "1080p"}
        )
        is None
    )


def test_broken_verified_bound_records_cost_and_blocks_that_price_version(tmp_path):
    adapter = Priced("0.08")
    pricing = FlatPricing("0.04")
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"priced": adapter},
        pricing=pricing,
        limits=(True, Decimal("1"), Decimal("1")),
    )
    gateway.generate_text("violated provider contract")
    assert gateway.store.sum_cost() == Decimal("0.08")
    assert gateway.store.list_reservations()[0]["state"] == "settled_overrun"
    assert gateway.generate_text("must not repeat invalid bound")["mock"] is True
    assert adapter.calls == 1
    assert gateway.store.list_logs()[-1]["params"]["budget_reason"] == "untrusted_bound"
    pricing.amount = Decimal("0.10")
    assert gateway.generate_text("reviewed corrected price")["text"] == "live-2"


def test_missing_invoice_keeps_hold_even_when_output_validated(tmp_path):
    adapter = Priced("0")
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"priced": adapter},
        pricing=FlatPricing("0.04"),
        limits=(True, Decimal("0.05"), Decimal("1")),
    )
    assert gateway.generate_text("output but no invoice")["text"] == "live-1"
    assert gateway.store.sum_cost() == 0
    assert gateway.store.budget_totals(gateway.budget.today())["reserved"] == Decimal("0.04")
    assert gateway.store.list_reservations()[0]["state"] == "uncertain"
    assert gateway.generate_text("no invoice is not free budget")["mock"] is True
    assert adapter.calls == 1


def test_log_redaction_is_recursive_but_does_not_change_request_or_cache(tmp_path):
    import json

    image = "data:image/png;base64," + base64.b64encode(b"private raw media pixels").decode()
    signed = "https://user:password@cdn.test/video.mp4?opaque=PRIVATE_QUERY_VALUE#PRIVATE_FRAGMENT"
    nested = {
        "reference": image,
        "source": signed,
        "headers": {"Authorization": "Bearer PRIVATE_AUTH", "Cookie": "PRIVATE_COOKIE"},
    }
    seen = []

    class Echo(Priced):
        def invoke(self, call):
            seen.append(call)
            return AdapterResult("priced", call.model, {"uri": signed}, Decimal("0.04"))

    adapter = Echo("0.04")
    gateway = build_gateway(
        tmp_path,
        routes=ROUTES,
        registry={"priced": adapter},
        pricing=FlatPricing("0.04"),
        limits=(True, Decimal("1"), Decimal("1")),
    )
    params = {"nested": [nested], "max_tokens": 7}
    prompt = f"use {image} and {signed}"
    assert gateway.generate_text(prompt, params=params)["uri"] == signed
    assert gateway.generate_text(prompt, params=params)["uri"] == signed
    assert len(seen) == 1  # Cache input/output semantics are untouched.
    assert seen[0].params["nested"][0] == nested
    assert seen[0].params["max_tokens"] == 7
    logs = json.dumps(gateway.store.list_logs())
    for forbidden in [
        "PRIVATE_QUERY_VALUE",
        "PRIVATE_FRAGMENT",
        "PRIVATE_AUTH",
        "PRIVATE_COOKIE",
        base64.b64encode(b"private raw media pixels").decode(),
        "user:password",
    ]:
        assert forbidden not in logs
    assert "cdn.test/video.mp4" in logs and "sha256=" in logs
    assert "image/png" in logs
    assert gateway.store.list_logs()[0]["params"]["max_tokens"] == 7


def test_conflicting_receipt_is_not_silently_treated_as_an_idempotent_replay(tmp_path):
    store = SqlStore.sqlite(tmp_path / "receipt.sqlite")
    store.reserve_budget(
        reservation_id="receipt",
        day="2026-11-01",
        created_at="now",
        estimate=Decimal("0.04"),
        total_cap=Decimal("1"),
        daily_cap=Decimal("1"),
        context={},
    )
    assert store.settle_budget("receipt", _log_row())
    with pytest.raises(GatewayError, match="conflicting"):
        store.settle_budget("receipt", _log_row("0.08"))
    assert store.sum_cost() == Decimal("0.04")


def test_cost_reservation_rounds_up_instead_of_below_its_bound(tmp_path):
    store = SqlStore.sqlite(tmp_path / "round-up.sqlite")
    decision = store.reserve_budget(
        reservation_id="fraction",
        day="2026-11-01",
        created_at="now",
        estimate=Decimal("0.0000011"),
        total_cap=Decimal("1"),
        daily_cap=Decimal("1"),
        context={},
    )
    assert decision["allowed"]
    assert store.budget_totals("2026-11-01")["reserved"] == Decimal("0.000002")


def test_nonpersistent_store_cannot_admit_billable_calls():
    store = SqlStore.sqlite(":memory:")
    decision = store.reserve_budget(
        reservation_id="unsafe",
        day="2026-11-01",
        created_at="now",
        estimate=Decimal("0.04"),
        total_cap=Decimal("1"),
        daily_cap=Decimal("1"),
        context={},
    )
    assert not decision["allowed"] and decision["reason"] == "nonpersistent_store"
    assert store.list_reservations() == []
