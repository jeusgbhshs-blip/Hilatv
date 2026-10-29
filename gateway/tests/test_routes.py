"""Route specificity and hot reload without restarting the process."""

from __future__ import annotations

from gateway.router import RouteTable
from gateway.tests.conftest import build_gateway, write_routes

SPECIFIC = """
version: 1
defaults:
  timeout_s: 5
routes:
  - id: close-en
    task: llm
    shot_type: close_up
    language: en
    primary: {provider: mock, model: close-en}
    fallbacks: []
  - id: fallback
    task: llm
    shot_type: "*"
    language: "*"
    primary: {provider: mock, model: generic}
    fallbacks: []
"""


def test_more_specific_shot_and_language_wins(tmp_path) -> None:
    table = RouteTable(write_routes(tmp_path, SPECIFIC))
    assert table.resolve("llm", "close_up", "en").id == "close-en"
    assert table.resolve("llm", "wide", "zh").id == "fallback"
    assert table.resolve("llm", "close_up", "zh").primary.model == "generic"
    assert table.resolve("llm", None, None).primary.model == "generic"


def test_route_file_hot_reload(tmp_path) -> None:
    path = write_routes(
        tmp_path,
        """
version: 1
defaults:
  timeout_s: 5
routes:
  - id: llm
    task: llm
    shot_type: "*"
    language: "*"
    primary: {provider: mock, model: alpha}
    fallbacks: []
""",
    )
    body = path.read_text(encoding="utf-8")
    gateway = build_gateway(tmp_path, routes=body)
    # build_gateway writes its own routes file; point the table at `path` instead.
    gateway.routes = RouteTable(path)
    gateway.generate_text("hi", seed=1)
    assert gateway.store.list_logs()[-1]["model"] == "alpha"
    path.write_text(
        """
version: 1
defaults:
  timeout_s: 5
routes:
  - id: llm
    task: llm
    shot_type: "*"
    language: "*"
    primary: {provider: mock, model: beta}
    fallbacks: []
""",
        encoding="utf-8",
    )
    gateway.generate_text("hi", seed=1)
    assert gateway.store.list_logs()[-1]["model"] == "beta"
    assert gateway.store.list_logs()[-1]["status"] == "ok"
