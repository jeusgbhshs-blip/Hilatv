"""Judge pixels stay out of the call log, and the cross-review route is addressable."""

from __future__ import annotations

from gateway.adapters.openai_compat import _user_content
from gateway.models import Invocation
from gateway.router import RouteTable, default_routes_path
from gateway.tests.conftest import build_gateway, mock_llm_routes


def test_image_bytes_are_not_stored(tmp_path) -> None:
    gateway = build_gateway(tmp_path, routes=mock_llm_routes())
    gateway.judge("score this frame", params={"image_b64": "abc123"}, seed=1)
    logged = gateway.store.list_logs()[0]["params"]
    assert "image_b64" not in logged
    assert logged["image_sha256"]
    assert "abc123" not in str(logged)


def test_vision_body_attaches_the_frame() -> None:
    call = Invocation(
        task="judge",
        prompt="score",
        model="qwen-vl-max",
        provider="qwen_vl",
        image_b64="aaaa",
    )
    content = _user_content(call)
    assert isinstance(content, list)
    assert content[1]["image_url"]["url"].endswith("aaaa")


def test_cross_review_route_is_specific() -> None:
    table = RouteTable(default_routes_path())
    assert table.resolve("judge", "cross_review", None).id == "judge-cross"
    assert table.resolve("judge", None, None).id == "judge-default"
    assert table.resolve("judge", None, None).fallbacks[-1].provider == "mock"
    assert table.resolve("judge", "cross_review", None).fallbacks[-1].provider == "mock"
