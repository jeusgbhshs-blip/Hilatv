"""Provider request contracts use real private images, without publishing them."""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from gateway.adapters.seedance import _submit_body
from gateway.adapters.seedream import SeedreamAdapter, _body
from gateway.errors import AdapterError
from gateway.image_inputs import image_data_url
from gateway.media_bytes import render_png
from gateway.models import Invocation
from gateway.storage import MemoryObjectStore
from gateway.tests.conftest import build_gateway
from gateway.tests.test_media_adapters import IMAGE_MODEL, MEDIA_ROUTES, VIDEO_MODEL


def _call(task="image", **params):
    return Invocation(
        task=task,
        prompt="无文字产品图",
        model=IMAGE_MODEL if task == "image" else VIDEO_MODEL,
        provider="seedream" if task == "image" else "seedance",
        project_id="p1",
        params=params,
    )


def _pixel(url):
    assert url.startswith("data:image/png;base64,")
    with Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))) as image:
        image.load()
        return image.getpixel((0, 0))


def test_seedream_reference_and_seedance_first_last_are_real_bytes():
    store = MemoryObjectStore()
    first = store.put("first.png", render_png(1, width=320, height=320), "image/png")
    last = store.put("last.png", render_png(2, width=320, height=320), "image/png")
    image = _body(_call(reference_images=[first, last]), store)
    assert _pixel(image["image"][0]) != _pixel(image["image"][1])
    video = _submit_body(_call("video", image_url=first, last_frame_url=last), store)
    frames = video["content"][1:]
    assert [frame["role"] for frame in frames] == ["first_frame", "last_frame"]
    assert _pixel(frames[0]["image_url"]["url"]) == _pixel(image["image"][0])
    assert _pixel(frames[1]["image_url"]["url"]) == _pixel(image["image"][1])
    assert video["watermark"] is False


def test_inputs_reject_public_urls_cross_bucket_and_unsupported_models():
    store = MemoryObjectStore()
    uri = store.put("image.png", render_png(1), "image/png")
    for forbidden in [
        "https://127.0.0.1/image.png",
        "oss://another/image.png",
        "file:///etc/passwd",
    ]:
        with pytest.raises(AdapterError):
            image_data_url(forbidden, _call(), store)
    fast = _call("video", image_url=uri, last_frame_url=uri)
    fast.model = "doubao-seedance-1-0-pro-fast-251015"
    with pytest.raises(AdapterError, match="first/last"):
        _submit_body(fast, store)
    old = _call(reference_images=[uri])
    old.model = "doubao-seedream-3-0-t2i-250415"
    with pytest.raises(AdapterError, match="does not support"):
        _body(old, store)
    with pytest.raises(AdapterError):
        _submit_body(_call("video", last_frame_url=uri), store)


def test_seedance_rejects_small_frames_and_fast_only_accepts_first_frame():
    store = MemoryObjectStore()
    small = store.put("small.png", render_png(1), "image/png")
    with pytest.raises(AdapterError, match="dimensions"):
        _submit_body(_call("video", image_url=small), store)
    square = store.put("square.png", render_png(1, width=320, height=320), "image/png")
    fast = _call("video", image_url=square)
    fast.model = "doubao-seedance-1-0-pro-fast-251015"
    assert _submit_body(fast, store)["content"][1]["role"] == "first_frame"


def test_local_images_are_scoped_to_project_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path))
    path = tmp_path / "p1" / "media" / "inputs" / "image.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(render_png(1))
    assert _pixel(image_data_url(path.as_uri(), _call(), None))
    wrong = _call()
    wrong.project_id = "p2"
    with pytest.raises(AdapterError):
        image_data_url(str(path), wrong, None)
    (path.parent / "alias.png").symlink_to(tmp_path / "outside.png")
    with pytest.raises(AdapterError):
        image_data_url(str(path.parent / "alias.png"), _call(), None)
    path.write_bytes(b"<svg>not a png</svg>")
    with pytest.raises(AdapterError):
        image_data_url(str(path), _call(), None)


def test_reference_bytes_reach_provider_but_never_gateway_logs(tmp_path):
    store = MemoryObjectStore()
    png = render_png(3)
    uri = store.put("input.png", png, "image/png")
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert _pixel(body["image"])
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png).decode()}]})

    from decimal import Decimal

    engine = build_gateway(
        tmp_path,
        routes=MEDIA_ROUTES,
        registry={
            "seedream": SeedreamAdapter(
                api_key="test-only", store=store, transport=httpx.MockTransport(handler)
            )
        },
        limits=(True, Decimal("20"), Decimal("20")),
    )
    engine.generate_image("产品无文字", project_id="p1", params={"reference_images": [uri]})
    assert len(seen) == 1
    logs = json.dumps(engine.store.list_logs())
    assert uri in logs
    assert "data:image" not in logs and base64.b64encode(png).decode() not in logs
