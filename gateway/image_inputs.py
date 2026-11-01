"""Private image inputs, converted only at the provider boundary.

No provider needs an unauthenticated HiLatv URL. Local inputs must already have
been copied by the worker into this project's input directory; caller-supplied
filesystem roots and remote HTTP downloads are deliberately unsupported.
"""

from __future__ import annotations

import base64
import io
import math
import os
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from gateway.aspects import ratio_parts
from gateway.errors import AdapterError, StorageError
from gateway.models import Invocation
from gateway.storage import ObjectStore, read_asset_bytes

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 36_000_000
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")


def project_input_root(project_id: str | None) -> Path:
    if not project_id or not _PROJECT_ID.fullmatch(project_id):
        raise AdapterError("reference image requires a valid project")
    raw = os.getenv("HILATV_PROJECT_DIR", "").strip()
    base = Path(raw) if raw else Path(tempfile.gettempdir()) / "hilatv-projects"
    project = base.resolve() / project_id
    root = project / "media" / "inputs"
    if project.is_symlink() or not root.resolve().is_relative_to(project):
        raise AdapterError("reference image directory is unsafe")
    return root


def image_data_url(
    uri: object,
    call: Invocation,
    store: ObjectStore | None,
    *,
    min_side: int = 15,
    max_side: int | None = None,
    aspect_range: tuple[float, float] = (1 / 16, 16),
    fit_ratio: str | None = None,
) -> str:
    if not isinstance(uri, str) or not uri.strip():
        raise AdapterError("reference image is missing")
    roots = (project_input_root(call.project_id),) if uri.startswith(("/", "file:")) else ()
    try:
        raw = read_asset_bytes(uri, store=store, allowed_roots=roots, max_bytes=MAX_IMAGE_BYTES)
    except StorageError as exc:
        raise AdapterError("reference image cannot be read safely") from exc
    try:
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            if (
                min(width, height) < min_side
                or width * height > MAX_IMAGE_PIXELS
                or (max_side is not None and max(width, height) > max_side)
                or not aspect_range[0] <= width / height <= aspect_range[1]
            ):
                raise AdapterError("reference image dimensions are unsupported")
            if image.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                raise AdapterError("reference image format is unsupported")
            if getattr(image, "n_frames", 1) != 1:
                raise AdapterError("animated reference images are unsupported")
            image.load()
            # Both providers accept PNG. Normalizing also strips metadata and
            # prevents an image filename or client MIME claim from deciding type.
            encoded = io.BytesIO()
            frame = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            if fit_ratio is not None:
                frame = _fit_frame(frame, fit_ratio, max_side=max_side)
            frame.save(encoded, "PNG")
            payload = encoded.getvalue()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise AdapterError("reference image is not decodable") from exc
    if len(payload) > MAX_IMAGE_BYTES:
        raise AdapterError("reference image exceeds provider size limit")
    return "data:image/png;base64," + base64.b64encode(payload).decode("ascii")


def _fit_frame(image: Image.Image, ratio: str, *, max_side: int | None) -> Image.Image:
    """Keep all reference pixels; add neutral padding instead of provider center-cropping."""
    a, b = ratio_parts(ratio)
    if image.width * b == image.height * a:
        return image
    unit = max(2, math.ceil(max(image.width / a, image.height / b) / 2) * 2)
    if max_side is not None:
        unit = min(unit, int(max_side / max(a, b) / 2) * 2)
    if unit < 2:
        raise AdapterError("reference image cannot fit the selected frame ratio")
    size = (a * unit, b * unit)
    frame = Image.new("RGB", size, (0, 0, 0))
    fitted = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
    pos = ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2)
    frame.paste(fitted, pos, fitted.getchannel("A") if "A" in fitted.getbands() else None)
    return frame
