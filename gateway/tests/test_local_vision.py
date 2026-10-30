"""Matting and relight stay on the local adapter and cost nothing."""

from __future__ import annotations

import base64
import io
from decimal import Decimal

import pytest
from PIL import Image

from gateway.cache import MemoryCache
from gateway.pricing import Pricing
from gateway.registry import build_registry
from gateway.router import RouteTable, default_routes_path
from gateway.service import Gateway
from gateway.store import SqlStore
from workers.nodes.n07_anchor.samples import marked_product


def _png_b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def test_packaged_routes_name_the_local_interfaces() -> None:
    table = RouteTable(default_routes_path())
    matte = table.resolve("matte", None, None)
    relight = table.resolve("relight", None, None)
    assert matte.primary.provider == "local_matting"
    assert matte.primary.model == "birefnet-rmbg-2.0-local"
    assert matte.fallbacks[-1].provider == "mock"
    assert relight.primary.provider == "local_relight"
    assert relight.primary.model == "ic-light-local"


def test_matte_and_relight_are_free_and_keep_opaque_pixels(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_LIVE", "0")
    monkeypatch.setenv("HILATV_BUDGET_CNY", "0")
    monkeypatch.delenv("S3_ENDPOINT", raising=False)
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)
    progress = tmp_path / "progress.md"
    progress.write_text(
        "## 告警（预算超限等，由网关自动追加）\n\n<!-- hilatv:alerts -->\n\n## 每日日志\n",
        encoding="utf-8",
    )
    gateway = Gateway(
        routes=RouteTable(default_routes_path()),
        store=SqlStore.sqlite(tmp_path / "gateway.sqlite"),
        cache=MemoryCache(),
        pricing=Pricing.load(),
        registry=build_registry(),
        limits_fn=lambda: (False, Decimal("0"), Decimal("0")),
        progress_path=progress,
        model_overrides_fn=lambda: {},
    )
    source = marked_product()
    matted = gateway.matte(
        "remove the flat background",
        project_id="p",
        node="n07_anchor",
        shot_id="pump",
        attempt=1,
        params={"image_b64": _png_b64(source)},
    )
    assert matted["edge_ok"] is True
    assert matted["interface"] == "birefnet-rmbg-2.0-local"
    scene = Image.new("RGB", (160, 120), (40, 80, 120))
    buffer = io.BytesIO()
    scene.save(buffer, format="PNG")
    lit = gateway.relight(
        "relight around the product",
        project_id="p",
        node="n07_anchor",
        shot_id="S01",
        attempt=1,
        params={
            "image_b64": _png_b64(buffer.getvalue()),
            "cutout_b64": matted["png_b64"],
            "x": 20,
            "y": 10,
        },
    )
    assert lit["interface"] == "ic-light-local"
    composite = Image.open(io.BytesIO(base64.b64decode(lit["png_b64"])))
    cutout = Image.open(io.BytesIO(base64.b64decode(matted["png_b64"]))).convert("RGBA")
    original = Image.open(io.BytesIO(source)).convert("RGB")
    dst = composite.convert("RGB").load()
    src = cutout.load()
    plain = original.load()
    matched = 0
    for y in range(cutout.height):
        for x in range(cutout.width):
            if src[x, y][3] != 255:
                continue
            assert dst[20 + x, 10 + y] == plain[x, y]
            matched += 1
    assert matched > 0
    corner = composite.getpixel((0, 0))
    shadow = composite.getpixel((20 + cutout.width // 2, 10 + cutout.height))
    assert sum(shadow[:3]) < sum(corner[:3])
    logs = gateway.store.list_logs()
    assert {row["provider"] for row in logs} == {"local_matting", "local_relight"}
    assert all(not row["live"] for row in logs)
    assert {Decimal(row["cost_cny"]) for row in logs} == {Decimal("0")}
    stored = logs[0]["params"]
    assert "image_b64" not in stored
    assert "cutout_b64" not in stored


@pytest.mark.parametrize("task", ["matte", "relight"])
def test_mock_fallback_still_runs_the_local_code(tmp_path, task: str) -> None:
    from gateway.tests.conftest import build_gateway, mock_llm_routes

    routes = (
        mock_llm_routes()
        + f"""
  - id: {task}
    task: {task}
    shot_type: "*"
    language: "*"
    primary: {{provider: mock, model: mock-{task}}}
    fallbacks: []
"""
    )
    gateway = build_gateway(tmp_path, routes=routes)
    params = {"image_b64": _png_b64(marked_product())}
    if task == "relight":
        scene = Image.new("RGB", (160, 120), (30, 30, 30))
        buffer = io.BytesIO()
        scene.save(buffer, format="PNG")
        params = {
            "image_b64": _png_b64(buffer.getvalue()),
            "cutout_b64": _png_b64(marked_product()),
            "x": 4,
            "y": 4,
        }
    result = gateway.execute(task, task, params=params, project_id="p", node="n07", shot_id="s")
    assert result["interface"].endswith("-local")
    assert gateway.store.list_logs()[-1]["provider"] == "mock"
    assert not gateway.store.list_logs()[-1]["live"]
