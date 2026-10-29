"""YAML route table. The file is re-read when its contents change."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from gateway.constants import TASKS
from gateway.errors import GatewayError
from gateway.logging import log_event

_PACKAGE = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Endpoint:
    provider: str
    model: str


@dataclass(frozen=True)
class Route:
    id: str
    task: str
    shot_type: str
    language: str
    timeout_s: float
    primary: Endpoint
    fallbacks: tuple[Endpoint, ...]

    def chain(self) -> tuple[Endpoint, ...]:
        return (self.primary, *self.fallbacks)

    def fingerprint(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "primary": {"provider": self.primary.provider, "model": self.primary.model},
            "fallbacks": [
                {"provider": item.provider, "model": item.model} for item in self.fallbacks
            ],
            "timeout_s": self.timeout_s,
        }


class RouteTable:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._digest: str | None = None
        self._failed_digest: str | None = None
        self._routes: list[Route] = []
        self._default_timeout = 60.0

    def resolve(self, task: str, shot_type: str | None, language: str | None) -> Route:
        self.refresh()
        if task not in TASKS:
            raise GatewayError(f"unknown task: {task}")
        best: Route | None = None
        best_score = -1
        for route in self._routes:
            if route.task != task:
                continue
            score = _score(route, shot_type, language)
            if score is None:
                continue
            if score > best_score:
                best = route
                best_score = score
        if best is None:
            raise GatewayError(
                f"no route for task={task} shot_type={shot_type} language={language}"
            )
        return best

    def refresh(self) -> None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            if self._routes:
                self._log_once(None, exc)
                return
            raise GatewayError(f"cannot read routes: {self.path}") from exc
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest == self._digest:
            return
        try:
            routes, default_timeout = _parse(text, self._default_timeout)
        except Exception as exc:
            if self._routes:
                self._log_once(digest, exc)
                return
            raise GatewayError(f"invalid routes file {self.path}: {exc}") from exc
        self._routes = routes
        self._default_timeout = default_timeout
        self._digest = digest
        self._failed_digest = None

    def _log_once(self, digest: str | None, exc: Exception) -> None:
        if digest is not None and digest == self._failed_digest:
            return
        self._failed_digest = digest
        log_event("route_reload_failed", path=str(self.path), error=str(exc))


def default_routes_path() -> Path:
    override = os.getenv("HILATV_ROUTES_PATH", "").strip()
    if override:
        return Path(override)
    return _PACKAGE / "routes.yaml"


def _parse(text: str, previous_timeout: float) -> tuple[list[Route], float]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise GatewayError("routes file must be a mapping")
    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise GatewayError("routes defaults must be a mapping")
    timeout = float(defaults.get("timeout_s") or previous_timeout or 60)
    raw_routes = data.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise GatewayError("routes file needs a non-empty routes list")
    routes: list[Route] = []
    for index, raw in enumerate(raw_routes):
        if not isinstance(raw, dict):
            raise GatewayError(f"route {index} must be a mapping")
        task = str(raw.get("task") or "")
        if task not in TASKS:
            raise GatewayError(f"route {index} has unknown task {task}")
        primary = _endpoint(raw.get("primary"), f"route {index} primary")
        fallbacks_raw = raw.get("fallbacks") or []
        if not isinstance(fallbacks_raw, list):
            raise GatewayError(f"route {index} fallbacks must be a list")
        fallbacks = tuple(
            _endpoint(item, f"route {index} fallback {pos}")
            for pos, item in enumerate(fallbacks_raw)
        )
        routes.append(
            Route(
                id=str(raw.get("id") or f"{task}-{index}"),
                task=task,
                shot_type=str(raw.get("shot_type") or "*"),
                language=str(raw.get("language") or "*"),
                timeout_s=float(raw.get("timeout_s") or timeout),
                primary=primary,
                fallbacks=fallbacks,
            )
        )
    return routes, timeout


def _endpoint(raw: object, label: str) -> Endpoint:
    if not isinstance(raw, dict) or "provider" not in raw or "model" not in raw:
        raise GatewayError(f"{label} needs provider and model")
    return Endpoint(provider=str(raw["provider"]), model=str(raw["model"]))


def _matches(pattern: str, value: str | None) -> bool:
    return pattern == "*" or (value is not None and pattern == value)


def _score(route: Route, shot_type: str | None, language: str | None) -> int | None:
    if not _matches(route.shot_type, shot_type) or not _matches(route.language, language):
        return None
    score = 0
    if route.shot_type != "*":
        score += 2
    if route.language != "*":
        score += 1
    return score
