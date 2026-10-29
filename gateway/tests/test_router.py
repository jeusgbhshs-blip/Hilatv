"""Packaged route table loads. Hot reload and specificity are in test_routes.py."""

from __future__ import annotations

from gateway.router import RouteTable, default_routes_path


def test_default_llm_route_is_deepseek() -> None:
    route = RouteTable(default_routes_path()).resolve("llm", None, None)
    assert route.primary.provider == "deepseek"
    assert route.primary.model == "deepseek-chat"
    assert [item.provider for item in route.fallbacks] == ["dashscope", "ark"]
