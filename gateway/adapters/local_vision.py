"""Local matting and relight. No weights are downloaded and nothing is billed.

``matte`` is the BiRefNet / RMBG-2.0 slot: a later GPU adapter can replace
``matte_output`` without changing nodes. This build removes a flat background
through the Brand Kit cutout. ``relight`` is the IC-Light slot. It may darken
the set and add a contact shadow. It does not repaint opaque product pixels.
"""

from __future__ import annotations

import base64
import binascii
import io

from PIL import Image

from gateway.models import Invocation

_INTERFACE_MATTE = "birefnet-rmbg-2.0-local"
_INTERFACE_RELIGHT = "ic-light-local"


def invoke_local(call: Invocation) -> dict[str, object]:
    if call.task == "relight":
        return relight_output(call)
    return matte_output(call)


def matte_output(call: Invocation) -> dict[str, object]:
    raw = _decode(call.image_b64)
    if raw is None:
        return _matte_fail("图片无法读取。请更换图片")
    from workers.brand_kit.matting import ReplaceImageError, matte

    try:
        cut = matte(raw)
    except ReplaceImageError as exc:
        return _matte_fail(str(exc))
    return {
        "mock": True,
        "task": "matte",
        "interface": _INTERFACE_MATTE,
        "png_b64": base64.b64encode(cut.png).decode("ascii"),
        "width": cut.width,
        "height": cut.height,
        "edge_ok": cut.edge.ok,
        "edge_message": cut.edge.message,
        "jagged": cut.edge.jagged,
        "leftover_background": cut.edge.leftover_background,
    }


def relight_output(call: Invocation) -> dict[str, object]:
    scene = _open(_decode(call.image_b64))
    cutout = _open(_decode(call.cutout_b64))
    if scene is None or cutout is None:
        return _relight_fail("图片无法读取。请更换图片")
    try:
        x = int(call.params.get("x"))
        y = int(call.params.get("y"))
    except (TypeError, ValueError):
        return _relight_fail("合成位置无效。请更换图片")
    if x < 0 or y < 0 or x + cutout.width > scene.width or y + cutout.height > scene.height:
        return _relight_fail("产品图放不进场景。请更换图片")
    framed = _relight(scene.convert("RGBA"), cutout.convert("RGBA"), x, y)
    return {
        "mock": True,
        "task": "relight",
        "interface": _INTERFACE_RELIGHT,
        "png_b64": base64.b64encode(_png(framed)).decode("ascii"),
        "width": framed.width,
        "height": framed.height,
        "x": x,
        "y": y,
    }


def _relight(scene: Image.Image, cutout: Image.Image, x: int, y: int) -> Image.Image:
    """Shadow and a short reflection under the cutout. Opaque RGB is copied back."""

    out = scene.copy()
    pixels = out.load()
    src = cutout.load()
    band_top = y + cutout.height
    for row in range(band_top, min(out.height, band_top + 8)):
        fade = 1 - (row - band_top) / 8
        for col in range(x, min(out.width, x + cutout.width)):
            red, green, blue, alpha = pixels[col, row]
            factor = 1 - 0.45 * fade
            pixels[col, row] = (
                int(red * factor),
                int(green * factor),
                int(blue * factor),
                alpha,
            )
    reflect = min(out.height, band_top + 12)
    for row in range(min(out.height, band_top + 8), reflect):
        for col in range(x + cutout.width // 4, min(out.width, x + 3 * cutout.width // 4)):
            red, green, blue, alpha = pixels[col, row]
            pixels[col, row] = (
                min(255, red + 12),
                min(255, green + 12),
                min(255, blue + 12),
                alpha,
            )
    out.paste(cutout, (x, y), cutout)
    for py in range(cutout.height):
        for px in range(cutout.width):
            red, green, blue, alpha = src[px, py]
            if alpha != 255:
                continue
            pixels[x + px, y + py] = (red, green, blue, 255)
    return out


def _matte_fail(message: str) -> dict[str, object]:
    return {
        "mock": True,
        "task": "matte",
        "interface": _INTERFACE_MATTE,
        "png_b64": "",
        "width": 0,
        "height": 0,
        "edge_ok": False,
        "edge_message": message,
        "jagged": False,
        "leftover_background": False,
    }


def _relight_fail(message: str) -> dict[str, object]:
    return {
        "mock": True,
        "task": "relight",
        "interface": _INTERFACE_RELIGHT,
        "png_b64": "",
        "width": 0,
        "height": 0,
        "x": 0,
        "y": 0,
        "edge_message": message,
    }


def _decode(value: object) -> bytes | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def _open(raw: bytes | None) -> Image.Image | None:
    if not raw:
        return None
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        return None
    return image


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class LocalMattingAdapter:
    """Gateway adapter id ``local_matting``. Billable stays false so CI can run it."""

    provider = "local_matting"
    billable = False
    tasks = frozenset({"matte"})

    def available(self) -> bool:
        return True

    def invoke(self, call: Invocation):  # type: ignore[no-untyped-def]
        from decimal import Decimal

        from gateway.models import AdapterResult

        return AdapterResult(
            provider=self.provider,
            model=call.model or "birefnet-rmbg-2.0-local",
            output=matte_output(call),
            cost_cny=Decimal("0"),
        )


class LocalRelightAdapter:
    """Gateway adapter id ``local_relight``. Billable stays false."""

    provider = "local_relight"
    billable = False
    tasks = frozenset({"relight"})

    def available(self) -> bool:
        return True

    def invoke(self, call: Invocation):  # type: ignore[no-untyped-def]
        from decimal import Decimal

        from gateway.models import AdapterResult

        return AdapterResult(
            provider=self.provider,
            model=call.model or "ic-light-local",
            output=relight_output(call),
            cost_cny=Decimal("0"),
        )
