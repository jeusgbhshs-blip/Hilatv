"""Gateway entry points. Business code calls these, never a vendor SDK."""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from gateway.adapters.base import Adapter
from gateway.adapters.mock_adapter import MockAdapter
from gateway.budget import BudgetGuard, env_model_overrides, limits_from_env
from gateway.cache import Cache, make_cache_key, open_cache
from gateway.clock import SystemClock
from gateway.constants import DEFAULT_JSON_SYSTEM, NO_RENDERED_TEXT, TASKS
from gateway.errors import GatewayError
from gateway.models import AdapterResult, Invocation
from gateway.money import money
from gateway.pricing import Pricing
from gateway.registry import build_registry
from gateway.router import Endpoint, Route, RouteTable, default_routes_path
from gateway.schema_util import coerce_output, normalize_schema
from gateway.store import SqlStore, open_store_from_env

_SECRET = re.compile(r"key|secret|token|password", re.IGNORECASE)
_gateway: Gateway | None = None
_guard = threading.Lock()


class Gateway:
    def __init__(
        self,
        *,
        routes: RouteTable,
        store: SqlStore,
        cache: Cache,
        pricing: Pricing,
        registry: dict[str, Adapter],
        limits_fn: Any,
        clock: Any | None = None,
        progress_path: Path | None = None,
        cache_ttl_s: int = 86400,
        model_overrides_fn: Any | None = None,
        timezone: str = "Asia/Shanghai",
    ) -> None:
        self.routes = routes
        self.store = store
        self.cache = cache
        self.pricing = pricing
        self.registry = dict(registry)
        self.registry.setdefault("mock", MockAdapter())
        self.limits_fn = limits_fn
        self.clock = clock or SystemClock(timezone)
        self.cache_ttl_s = cache_ttl_s
        self.model_overrides_fn = model_overrides_fn or (lambda: {})
        self.tz = timezone
        self.budget = BudgetGuard(
            store=store,
            limits_fn=limits_fn,
            clock=self.clock,
            progress_path=progress_path,
            tz=timezone,
        )

    @classmethod
    def from_env(cls) -> Gateway:
        progress = os.getenv("HILATV_PROGRESS_PATH", "").strip()
        ttl_raw = os.getenv("HILATV_CACHE_TTL_S", "86400").strip() or "86400"
        redis_url = os.getenv("REDIS_URL", "").strip()
        return cls(
            routes=RouteTable(default_routes_path()),
            store=open_store_from_env(),
            cache=open_cache(redis_url or None),
            pricing=Pricing.load(),
            registry=build_registry(),
            limits_fn=limits_from_env,
            progress_path=Path(progress) if progress else _default_progress(),
            cache_ttl_s=int(ttl_raw),
            model_overrides_fn=env_model_overrides,
        )

    def generate_text(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | dict[str, Any] | None = None,
        seed: int | None = None,
        shot_type: str | None = None,
        language: str | None = None,
        system: str | None = None,
        project_id: str | None = None,
        node: str | None = None,
        shot_id: str | None = None,
        attempt: int | None = None,
        temperature: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.execute(
            "llm",
            prompt,
            schema=schema,
            seed=seed,
            shot_type=shot_type,
            language=language,
            system=system,
            project_id=project_id,
            node=node,
            shot_id=shot_id,
            attempt=attempt,
            temperature=temperature,
            params=params,
        )

    def generate_image(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return self.execute("image", prompt, **kwargs)

    def generate_video(
        self,
        prompt: str,
        *,
        duration_s: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        params = dict(kwargs.pop("params", None) or {})
        if duration_s is not None:
            params["duration_s"] = duration_s
        return self.execute("video", prompt, params=params, **kwargs)

    def tts(self, text: str, *, voice: str | None = None, **kwargs: Any) -> dict[str, Any]:
        params = dict(kwargs.pop("params", None) or {})
        if voice is not None:
            params["voice"] = voice
        return self.execute("tts", text, params=params, **kwargs)

    def asr(self, audio_uri: str, **kwargs: Any) -> dict[str, Any]:
        return self.execute("asr", audio_uri, **kwargs)

    def music(
        self,
        prompt: str,
        *,
        duration_s: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        params = dict(kwargs.pop("params", None) or {})
        if duration_s is not None:
            params["duration_s"] = duration_s
        return self.execute("music", prompt, params=params, **kwargs)

    def judge(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        return self.execute("judge", prompt, **kwargs)

    def content_safety(self, text: str, **kwargs: Any) -> dict[str, Any]:
        params = dict(kwargs.pop("params", None) or {})
        params.setdefault("stage", "input")
        return self.execute("content_safety", text, params=params, **kwargs)

    def execute(
        self,
        task: str,
        prompt: str,
        *,
        schema: type[BaseModel] | dict[str, Any] | None = None,
        seed: int | None = None,
        shot_type: str | None = None,
        language: str | None = None,
        system: str | None = None,
        project_id: str | None = None,
        node: str | None = None,
        shot_id: str | None = None,
        attempt: int | None = None,
        temperature: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if task not in TASKS:
            raise GatewayError(f"unknown task: {task}")
        model_cls, json_schema, schema_name = normalize_schema(schema)
        prompt, negative = _prepare_prompt(task, prompt)
        clean_params = _public_params(dict(params or {}))
        image_b64 = clean_params.pop("image_b64", None)
        if isinstance(image_b64, str) and image_b64:
            clean_params["image_sha256"] = hashlib.sha256(image_b64.encode("utf-8")).hexdigest()
        else:
            image_b64 = None
        if seed is None and clean_params.get("seed") is not None:
            seed = int(clean_params["seed"])
        route = self._with_overrides(self.routes.resolve(task, shot_type, language))
        clean_params["route_id"] = route.id
        candidates = self._candidates(route, task)
        if task == "content_safety":
            candidates = self._content_safety_candidates(candidates)
        billable = [(endpoint, adapter) for endpoint, adapter in candidates if adapter.billable]
        mode = "live" if billable else "mock"
        system_effective = system
        if system_effective is None and json_schema is not None and task in {"llm", "judge"}:
            system_effective = DEFAULT_JSON_SYSTEM
        temperature_effective = temperature
        if temperature_effective is None and task in {"llm", "judge"}:
            temperature_effective = 0.2
        max_output = clean_params.get("max_tokens")
        max_output_tokens = int(max_output) if max_output is not None else None

        payload = {
            "v": 1,
            "mode": mode,
            "task": task,
            "prompt": prompt,
            "system": system_effective,
            "seed": seed,
            "shot_type": shot_type,
            "language": language,
            "schema": json_schema,
            "params": clean_params,
            "negative_prompt": negative,
            "temperature": temperature_effective,
            "route": route.fingerprint(),
        }
        cache_key = make_cache_key(payload)
        base = Invocation(
            task=task,
            prompt=prompt,
            model=route.primary.model,
            provider=route.primary.provider,
            system=system_effective,
            seed=seed,
            temperature=temperature_effective,
            timeout_s=route.timeout_s,
            json_schema=json_schema,
            schema_name=schema_name,
            params=clean_params,
            negative_prompt=negative,
            project_id=project_id,
            node=node,
            shot_id=shot_id,
            attempt=attempt,
            shot_type=shot_type,
            language=language,
            image_b64=image_b64 if isinstance(image_b64, str) else None,
        )
        started = time.perf_counter()
        cached = self.cache.get(cache_key)
        if cached is not None and isinstance(cached.get("output"), dict):
            hit = replace(
                base,
                provider=str(cached.get("provider") or "cache"),
                model=str(cached.get("model") or base.model),
            )
            self._log(
                hit,
                provider=hit.provider,
                model=hit.model,
                cost=money(0),
                status="cache_hit",
                latency_ms=_ms(started),
                cache_hit=True,
                live=False,
                output=cached["output"],
            )
            return cached["output"]

        if billable:
            estimate = self.pricing.estimate(
                billable[0][0].model,
                prompt,
                system=system_effective,
                schema=json_schema,
                max_output_tokens=max_output_tokens,
                task=task,
                params=clean_params,
            )
            decision = self.budget.evaluate(estimate)
            if not decision.allowed:
                if decision.notify:
                    self.budget.notify(
                        decision,
                        project_id=project_id,
                        node=node,
                        shot_id=shot_id,
                        attempt=attempt,
                    )
                if task == "content_safety":
                    raise GatewayError(
                        "content safety unreviewed: budget blocked the live moderator"
                    )
                return self._serve_mock(
                    base,
                    model=f"mock-{task}",
                    reason="budget_exceeded",
                    cache_key=None,
                    model_cls=model_cls,
                    json_schema=json_schema,
                )
            last_error: Exception | None = None
            for index, (endpoint, adapter) in enumerate(candidates, start=1):
                invocation = replace(
                    base,
                    model=endpoint.model,
                    provider=endpoint.provider,
                    attempt=index,
                    timeout_s=route.timeout_s,
                )
                try_started = time.perf_counter()
                try:
                    result = adapter.invoke(invocation)
                    output = coerce_output(result.output, model_cls, json_schema)
                except Exception as exc:
                    self._log(
                        invocation,
                        provider=endpoint.provider,
                        model=endpoint.model,
                        cost=money(0),
                        status="error",
                        latency_ms=_ms(try_started),
                        live=bool(adapter.billable),
                        error=exc,
                    )
                    last_error = exc
                    continue
                cost = self._priced(result, invocation, adapter.billable)
                self._log(
                    invocation,
                    provider=result.provider,
                    model=result.model,
                    cost=cost,
                    status="ok",
                    latency_ms=_ms(try_started),
                    live=bool(adapter.billable),
                    output=output,
                )
                self.cache.set(
                    cache_key,
                    {"output": output, "provider": result.provider, "model": result.model},
                    self.cache_ttl_s,
                )
                return output
            raise GatewayError(f"all adapters failed for {task}") from last_error

        mock_endpoint = next(
            (endpoint for endpoint, adapter in candidates if not adapter.billable),
            None,
        )
        model_name = mock_endpoint.model if mock_endpoint is not None else f"mock-{task}"
        return self._serve_mock(
            base,
            model=model_name,
            reason=None,
            cache_key=cache_key,
            model_cls=model_cls,
            json_schema=json_schema,
        )

    def _serve_mock(
        self,
        base: Invocation,
        *,
        model: str,
        reason: str | None,
        cache_key: str | None,
        model_cls: type[BaseModel] | None,
        json_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        adapter = self.registry["mock"]
        invocation = replace(base, provider="mock", model=model, attempt=base.attempt or 1)
        started = time.perf_counter()
        try:
            result = adapter.invoke(invocation)
            output = coerce_output(result.output, model_cls, json_schema)
        except Exception as exc:
            self._log(
                invocation,
                provider="mock",
                model=model,
                cost=money(0),
                status="error",
                latency_ms=_ms(started),
                live=False,
                fallback_reason=reason,
                error=exc,
            )
            raise GatewayError("mock output failed validation") from exc
        self._log(
            invocation,
            provider="mock",
            model=model,
            cost=money(0),
            status="ok",
            latency_ms=_ms(started),
            live=False,
            fallback_reason=reason,
            output=output,
        )
        if cache_key is not None and reason != "budget_exceeded":
            self.cache.set(
                cache_key,
                {"output": output, "provider": "mock", "model": model},
                self.cache_ttl_s,
            )
        return output

    def _content_safety_candidates(
        self, candidates: list[tuple[Endpoint, Adapter]]
    ) -> list[tuple[Endpoint, Adapter]]:
        """Live moderation never falls through to the mock adapter."""

        live, _, _ = self.limits_fn()
        if not live:
            return candidates
        live_only = [item for item in candidates if item[1].billable and item[1].provider != "mock"]
        if not live_only:
            raise GatewayError("content safety unreviewed: live moderator is not configured")
        return live_only

    def _candidates(self, route: Route, task: str) -> list[tuple[Endpoint, Adapter]]:
        live, _, _ = self.limits_fn()
        found: list[tuple[Endpoint, Adapter]] = []
        for endpoint in route.chain():
            adapter = self.registry.get(endpoint.provider)
            if adapter is None or not adapter.available():
                continue
            if task not in adapter.tasks:
                continue
            if adapter.billable and not live:
                continue
            found.append((endpoint, adapter))
        return found

    def _with_overrides(self, route: Route) -> Route:
        overrides = self.model_overrides_fn() or {}

        def apply(endpoint: Endpoint) -> Endpoint:
            name = str(overrides.get(endpoint.provider) or "").strip()
            if name:
                return Endpoint(endpoint.provider, name)
            return endpoint

        return Route(
            id=route.id,
            task=route.task,
            shot_type=route.shot_type,
            language=route.language,
            timeout_s=route.timeout_s,
            primary=apply(route.primary),
            fallbacks=tuple(apply(item) for item in route.fallbacks),
        )

    def _priced(self, result: AdapterResult, call: Invocation, billable: bool) -> Decimal:
        usage = result.usage or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        if prompt_tokens or completion_tokens:
            return self.pricing.from_usage(result.model, usage)
        if _media_usage(usage):
            cost = self.pricing.from_usage(result.model, usage)
            if cost:
                return cost
        if result.cost_cny:
            return money(result.cost_cny)
        if billable:
            return self.pricing.estimate(
                call.model,
                call.prompt,
                system=call.system,
                schema=call.json_schema,
                task=call.task,
                params=call.params,
            )
        return money(0)

    def _log(
        self,
        call: Invocation,
        *,
        provider: str,
        model: str,
        cost: Decimal,
        status: str,
        latency_ms: int,
        cache_hit: bool = False,
        live: bool = False,
        fallback_reason: str | None = None,
        output: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        now = self.clock.now()
        self.store.insert_log(
            {
                "created_at": now.isoformat(),
                "day": now.astimezone(ZoneInfo(self.tz)).date().isoformat(),
                "project_id": call.project_id,
                "node": call.node,
                "shot_id": call.shot_id,
                "attempt": call.attempt,
                "task": call.task,
                "provider": provider,
                "model": model,
                "params": _stored_params(call),
                "latency_ms": latency_ms,
                "cost_cny": money(cost),
                "status": status,
                "cache_hit": cache_hit,
                "qa_score": None,
                "live": live,
                "fallback_reason": fallback_reason,
                "output": output,
                "error": None if error is None else str(error)[:500],
            }
        )


def get_gateway() -> Gateway:
    global _gateway
    with _guard:
        if _gateway is None:
            _gateway = Gateway.from_env()
        return _gateway


def reset_gateway() -> None:
    global _gateway
    with _guard:
        _gateway = None


def generate_text(prompt: str, **kwargs: Any) -> dict[str, Any]:
    gateway = kwargs.pop("gateway", None)
    return (gateway or get_gateway()).generate_text(prompt, **kwargs)


def generate_image(prompt: str, **kwargs: Any) -> dict[str, Any]:
    gateway = kwargs.pop("gateway", None)
    return (gateway or get_gateway()).generate_image(prompt, **kwargs)


def generate_video(prompt: str, **kwargs: Any) -> dict[str, Any]:
    gateway = kwargs.pop("gateway", None)
    return (gateway or get_gateway()).generate_video(prompt, **kwargs)


def tts(text: str, **kwargs: Any) -> dict[str, Any]:
    gateway = kwargs.pop("gateway", None)
    return (gateway or get_gateway()).tts(text, **kwargs)


def asr(audio_uri: str, **kwargs: Any) -> dict[str, Any]:
    gateway = kwargs.pop("gateway", None)
    return (gateway or get_gateway()).asr(audio_uri, **kwargs)


def music(prompt: str, **kwargs: Any) -> dict[str, Any]:
    gateway = kwargs.pop("gateway", None)
    return (gateway or get_gateway()).music(prompt, **kwargs)


def judge(prompt: str, **kwargs: Any) -> dict[str, Any]:
    gateway = kwargs.pop("gateway", None)
    return (gateway or get_gateway()).judge(prompt, **kwargs)


def content_safety(text: str, **kwargs: Any) -> dict[str, Any]:
    gateway = kwargs.pop("gateway", None)
    return (gateway or get_gateway()).content_safety(text, **kwargs)


def _prepare_prompt(task: str, prompt: str) -> tuple[str, str | None]:
    if task not in {"image", "video"}:
        return prompt, None
    if NO_RENDERED_TEXT in prompt:
        return prompt, NO_RENDERED_TEXT
    return f"{prompt}\n\nNegative: {NO_RENDERED_TEXT}", NO_RENDERED_TEXT


def _public_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if not _SECRET.search(str(key))}


def _stored_params(call: Invocation) -> dict[str, Any]:
    stored = dict(call.params)
    stored.update(
        {
            "prompt": call.prompt,
            "system": call.system,
            "seed": call.seed,
            "temperature": call.temperature,
            "shot_type": call.shot_type,
            "language": call.language,
            "schema": call.schema_name,
            "negative_prompt": call.negative_prompt,
            "timeout_s": call.timeout_s,
        }
    )
    return stored


def _media_usage(usage: dict[str, Any]) -> bool:
    for key in ("images", "video_seconds", "characters"):
        value = usage.get(key)
        if value not in (None, 0, 0.0, "0"):
            return True
    return False


def _ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _default_progress() -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / "progress.md"
