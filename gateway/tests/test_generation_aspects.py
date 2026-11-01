"""Provider payloads and encoded pixels follow the saved target frame."""

import base64
import io
import json
import subprocess
import tempfile
from pathlib import Path
from typing import get_args

import pytest
from PIL import Image

from gateway.adapters.mock_adapter import MockAdapter
from gateway.adapters.seedance import _submit_body
from gateway.adapters.seedream import SeedreamAdapter, _body
from gateway.aspects import IMAGE_SIZES, image_size_for_ratio
from gateway.errors import AdapterError
from gateway.media_bytes import decode_png
from gateway.models import Invocation
from gateway.storage import MemoryObjectStore
from workers.schemas.generation import AspectRatio

IMAGE_MODEL = "doubao-seedream-4-0-250828"
VIDEO_MODEL = "doubao-seedance-1-0-pro-250528"


def call(task, ratio):
    return Invocation(
        task=task,
        prompt="product, no text",
        provider="seedream" if task == "image" else "seedance",
        model=IMAGE_MODEL if task == "image" else VIDEO_MODEL,
        project_id="aspect-test",
        seed=7,
        params={"ratio": ratio, "duration_s": 0.2},
    )


def test_shared_ratio_contract_and_image_pixel_bounds():
    assert set(get_args(AspectRatio)) == set(IMAGE_SIZES)
    for ratio in IMAGE_SIZES:
        request = call("image", ratio)
        body = _body(request)
        width, height = map(int, body["size"].split("x"))
        a, b = map(int, ratio.split(":"))
        assert width * b == height * a
        assert 921600 <= width * height <= 16777216
        assert body["size"] == image_size_for_ratio(ratio)

        class BoundPricing:
            def upper_bound(self, model, prompt, **kwargs):
                assert kwargs["params"]["size"] == body["size"]
                return 1

        assert SeedreamAdapter().cost_upper_bound(request, BoundPricing()) == 1
    conflict = call("image", "4:3")
    conflict.params["size"] = "1K"
    with pytest.raises(AdapterError, match="conflicts"):
        _body(conflict)


def test_first_frame_keeps_all_corners_and_non_native_ratio_follows_actual_frame():
    source = Image.new("RGB", (400, 400), "red")
    source.paste("green", (200, 0, 400, 200))
    source.paste("blue", (0, 200, 200, 400))
    source.paste("yellow", (200, 200, 400, 400))
    image = io.BytesIO()
    source.save(image, "PNG")
    store = MemoryObjectStore()
    uri = store.put("reference.png", image.getvalue(), "image/png")
    request = call("video", "2:3")
    request.params["image_url"] = uri
    body = _submit_body(request, store)
    assert body["ratio"] == "adaptive"
    frame = body["content"][1]["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(frame.split(",", 1)[1]))) as decoded:
        assert decoded.width * 3 == decoded.height * 2
        left, top, right, bottom = decoded.getbbox()
        assert top > 0 and bottom < decoded.height
        assert decoded.getpixel((left, top)) == (255, 0, 0)
        assert decoded.getpixel((right - 1, top)) == (0, 128, 0)
        assert decoded.getpixel((left, bottom - 1)) == (0, 0, 255)
        assert decoded.getpixel((right - 1, bottom - 1)) == (255, 255, 0)
    with pytest.raises(AdapterError, match="first-frame"):
        _submit_body(call("video", "2:3"), store)


@pytest.mark.parametrize("ratio", ["9:16", "4:3", "2:3", "21:9"])
def test_mock_encodes_requested_image_and_video_shape_with_distinct_assets(ratio):
    store = MemoryObjectStore()
    adapter = MockAdapter(store)
    requested = adapter.invoke(call("image", ratio)).output
    other = adapter.invoke(call("image", "16:9")).output
    assert requested["uri"] != other["uri"]
    width, height, _ = decode_png(store.get(requested["uri"]))
    a, b = map(int, ratio.split(":"))
    assert width * b == height * a
    video = adapter.invoke(call("video", ratio)).output
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "mock.mp4"
        path.write_bytes(store.get(video["uri"]))
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            check=True,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        assert stream["width"] * b == stream["height"] * a
