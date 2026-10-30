"""Pixel rules for N9 and N11.

Resolution, composition, face count, and painted writing are measured here.
Writing is a stroke-band check, not a cloud OCR call. Faces are skin blobs
plus dark eye blobs, not a face-recognition SDK.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from workers.qa.pixels import (
    cosine,
    foreground_mask,
    luma_at,
    mask_area,
    pack,
    pixel,
    shape_similarity,
    touches_border,
)
from workers.qa.settings import (
    deform_min_similarity,
    face_min_similarity,
    flicker_delta,
    flicker_neighbor,
)
from workers.qa.settings import (
    min_edge as configured_min_edge,
)

# Long edge. 320×180 passes; a 96×54 plate does not.
# Anti-aliased glyphs jump by about 40 levels, not a hard 70.
TEXT_JUMP = 40
TEXT_SPAN = 64
TEXT_TRANSITIONS = 10
TEXT_ROWS = 5
BAR_LUMA = 16
BAR_FRACTION = 0.06


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str


def inspect_image(
    image: Image.Image,
    *,
    anchor: Image.Image | None = None,
    expected_faces: int = 0,
    min_edge: int | None = None,
    check_composition: bool = True,
) -> list[Finding]:
    if min_edge is None:
        min_edge = configured_min_edge()
    buf, width, height = pack(image)
    found: list[Finding] = []
    if max(width, height) < min_edge:
        found.append(Finding("low_resolution", f"{width}x{height} long edge is under {min_edge}px"))
    if _black_bars(buf, width, height):
        found.append(Finding("black_bar", "a frame edge is a solid black bar"))
    text = _text_band(buf, width, height)
    if text is not None:
        found.append(text)
    if _watermark(buf, width, height):
        found.append(Finding("watermark", "periodic mark in a corner"))
    mask = foreground_mask(buf, width, height)
    if check_composition:
        composition = _composition(mask, width, height)
        if composition is not None:
            found.append(composition)
    if anchor is not None:
        similarity = shape_similarity(image, anchor)
        if similarity < deform_min_similarity():
            found.append(
                Finding("product_deform", f"shape similarity {similarity:.3f} is below the anchor")
            )
    found.extend(_faces(buf, width, height, expected_faces=expected_faces))
    return _unique(found)


def inspect_frames(
    frames: list[Image.Image],
    *,
    anchor: Image.Image | None = None,
    expected_faces: int = 0,
    min_edge: int | None = None,
) -> tuple[list[Finding], list[bool]]:
    """Return clip findings and whether each frame is usable in a splice."""

    if not frames:
        return [Finding("low_resolution", "video has no frames")], []
    per_frame: list[list[Finding]] = []
    for frame in frames:
        per_frame.append(
            inspect_image(
                frame,
                anchor=anchor,
                expected_faces=expected_faces,
                min_edge=min_edge,
            )
        )
    flicker_at = _flicker_indexes(frames)
    face_gap = _face_gap(frames, anchor, expected_faces=expected_faces)
    good: list[bool] = []
    for index, findings in enumerate(per_frame):
        bad = bool(findings) or index in flicker_at
        good.append(not bad)
    merged: list[Finding] = []
    for findings in per_frame:
        merged.extend(findings)
    if flicker_at:
        merged.append(Finding("flicker", f"frame jump at {sorted(flicker_at)}"))
    if face_gap is not None:
        merged.append(face_gap)
        good = [False] * len(good)
    return _unique(merged), good


def _unique(findings: list[Finding]) -> list[Finding]:
    seen: set[str] = set()
    ordered: list[Finding] = []
    for item in findings:
        if item.code in seen:
            continue
        seen.add(item.code)
        ordered.append(item)
    return ordered


def _black_bars(buf: bytes, width: int, height: int) -> bool:
    if width < 8 or height < 8:
        return False

    def row_dark(y: int) -> bool:
        total = sum(luma_at(buf, width, x, y) for x in range(width))
        return total / width <= BAR_LUMA

    def col_dark(x: int) -> bool:
        total = sum(luma_at(buf, width, x, y) for y in range(height))
        return total / height <= BAR_LUMA

    def run(length: int, dark) -> int:
        count = 0
        for index in range(length):
            if not dark(index):
                break
            count += 1
        return count

    top = run(height, row_dark)
    bottom = run(height, lambda index: row_dark(height - 1 - index))
    left = run(width, col_dark)
    right = run(width, lambda index: col_dark(width - 1 - index))
    center = luma_at(buf, width, width // 2, height // 2)
    thick = (
        top >= height * BAR_FRACTION
        or bottom >= height * BAR_FRACTION
        or left >= width * BAR_FRACTION
        or right >= width * BAR_FRACTION
    )
    return thick and center > 40


def _text_band(buf: bytes, width: int, height: int) -> Finding | None:
    busy_rows: list[tuple[int, list[int]]] = []
    for y in range(height):
        jumps = _jumps(buf, width, y, threshold=TEXT_JUMP)
        if len(jumps) < TEXT_TRANSITIONS:
            continue
        span = jumps[-1] - jumps[0]
        if span < TEXT_SPAN:
            continue
        busy_rows.append((y, jumps))
    if len(busy_rows) < TEXT_ROWS:
        return None
    band = _longest_run([row for row, _ in busy_rows])
    if band < TEXT_ROWS:
        return None
    gaps: list[int] = []
    for _, jumps in busy_rows:
        gaps.extend(jumps[index + 1] - jumps[index] for index in range(len(jumps) - 1))
    if not gaps:
        return Finding("extra_text", "high-contrast writing")
    mean = sum(gaps) / len(gaps)
    variance = sum((gap - mean) ** 2 for gap in gaps) / len(gaps)
    spread = (variance**0.5) / mean if mean else 0
    # Real glyphs cluster near 0.8. Random strokes sit above 1.3.
    if spread > 1.0:
        return Finding("garbled_text", "broken stroke band")
    return Finding("extra_text", "readable writing painted into the frame")


def _jumps(buf: bytes, width: int, y: int, *, threshold: int) -> list[int]:
    jumps: list[int] = []
    previous = luma_at(buf, width, 0, y)
    for x in range(1, width):
        current = luma_at(buf, width, x, y)
        if abs(current - previous) > threshold:
            jumps.append(x)
            previous = current
    return jumps


def _longest_run(rows: list[int]) -> int:
    if not rows:
        return 0
    best = 1
    current = 1
    for previous, this in zip(rows, rows[1:], strict=False):
        if this == previous + 1:
            current += 1
            best = max(best, current)
        else:
            current = 1
    return best


def _watermark(buf: bytes, width: int, height: int) -> bool:
    tile_w = max(8, width // 6)
    tile_h = max(8, height // 6)
    corners = (
        (width - tile_w, height - tile_h, tile_w, tile_h),
        (0, height - tile_h, tile_w, tile_h),
        (width - tile_w, 0, tile_w, tile_h),
        (0, 0, tile_w, tile_h),
    )
    energies = [_edge_energy(buf, width, left, top, tw, th) for left, top, tw, th in corners]
    ranked = sorted(energies)
    quiet = ranked[len(ranked) // 2]
    for (left, top, tw, th), energy in zip(corners, energies, strict=True):
        if energy < 8 or energy < max(6.0, quiet * 2.5):
            continue
        if _periodic(buf, width, left, top, tw, th):
            return True
    return False


def _edge_energy(buf: bytes, width: int, left: int, top: int, tw: int, th: int) -> float:
    total = 0
    count = 0
    for y in range(top, top + th):
        for x in range(left, left + tw - 1):
            total += abs(luma_at(buf, width, x + 1, y) - luma_at(buf, width, x, y))
            count += 1
    return total / count if count else 0.0


def _periodic(buf: bytes, width: int, left: int, top: int, tw: int, th: int) -> bool:
    values: list[int] = []
    y = top + th // 2
    for x in range(left, left + tw - 1):
        values.append(abs(luma_at(buf, width, x + 1, y) - luma_at(buf, width, x, y)))
    if len(values) < 12:
        return False
    lag = 4
    pairs = list(zip(values, values[lag:], strict=False))
    if len(pairs) < 8:
        return False
    mean_a = sum(a for a, _ in pairs) / len(pairs)
    mean_b = sum(b for _, b in pairs) / len(pairs)
    num = sum((a - mean_a) * (b - mean_b) for a, b in pairs)
    den_a = sum((a - mean_a) ** 2 for a, _ in pairs)
    den_b = sum((b - mean_b) ** 2 for _, b in pairs)
    if den_a <= 0 or den_b <= 0:
        return False
    return num / ((den_a * den_b) ** 0.5) >= 0.45


def _composition(mask: bytearray, width: int, height: int) -> Finding | None:
    area = mask_area(mask)
    if area <= 0:
        return None
    fraction = area / (width * height)
    if fraction < 0.08:
        return Finding("bad_composition", f"subject covers {fraction:.2%} of the frame")
    if fraction > 0.82:
        return Finding("bad_composition", f"subject covers {fraction:.2%} of the frame")
    if touches_border(mask, width, height):
        return Finding("bad_composition", "subject is cut by the frame edge")
    return None


def _faces(buf: bytes, width: int, height: int, *, expected_faces: int) -> list[Finding]:
    mask = _skin_mask(buf, width, height)
    blobs = _components(mask, width, height, minimum=max(180, width * height // 80))
    valid = 0
    broken = 0
    for _cells, bbox in blobs:
        if _eyes(buf, width, bbox):
            valid += 1
        else:
            broken += 1
    if broken:
        return [Finding("face_collapse", "facial features do not form a stable face")]
    if valid != expected_faces:
        return [Finding("face_count", f"found {valid} faces, expected {expected_faces}")]
    return []


def _skin_mask(buf: bytes, width: int, height: int) -> bytearray:
    mask = bytearray(width * height)
    for y in range(height):
        for x in range(width):
            red, green, blue = pixel(buf, width, x, y)
            if (
                red > 155
                and green > 95
                and blue > 70
                and red > green + 18
                and red > blue + 28
                and red - green < 110
            ):
                mask[y * width + x] = 1
    return mask


def _components(
    mask: bytearray, width: int, height: int, *, minimum: int
) -> list[tuple[list[int], tuple[int, int, int, int]]]:
    seen = bytearray(width * height)
    found: list[tuple[list[int], tuple[int, int, int, int]]] = []
    for start in range(width * height):
        if not mask[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        cells: list[int] = []
        min_x = min_y = 10**9
        max_x = max_y = 0
        while stack:
            index = stack.pop()
            cells.append(index)
            x = index % width
            y = index // width
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            for nxt in (index - 1, index + 1, index - width, index + width):
                if nxt < 0 or nxt >= width * height or seen[nxt] or not mask[nxt]:
                    continue
                nx = nxt % width
                if abs(nx - x) > 1:
                    continue
                seen[nxt] = 1
                stack.append(nxt)
        if len(cells) >= minimum:
            found.append((cells, (min_x, min_y, max_x, max_y)))
    return found


def _eyes(buf: bytes, width: int, bbox: tuple[int, int, int, int]) -> bool:
    """True when the blob has two matched eyes. Eyes are holes in the skin mask."""

    min_x, min_y, max_x, max_y = bbox
    face_h = max(1, max_y - min_y)
    height = len(buf) // (width * 3)
    dark: list[int] = []
    for y in range(min_y, min(max_y + 1, height)):
        if y > min_y + int(face_h * 0.62):
            continue
        for x in range(min_x, min(max_x + 1, width)):
            if luma_at(buf, width, x, y) > 60:
                continue
            dark.append(y * width + x)
    if len(dark) < 6:
        return False
    dark_mask = bytearray(len(buf) // 3)
    for index in dark:
        dark_mask[index] = 1
    blobs = _components(dark_mask, width, max(1, max(dark) // width + 1), minimum=4)
    eyes = []
    for eye_cells, eye_box in blobs:
        ex0, ey0, ex1, ey1 = eye_box
        ew = ex1 - ex0 + 1
        eh = ey1 - ey0 + 1
        if eh <= 0 or ew / eh > 2.8:
            continue
        if not 4 <= len(eye_cells) <= 220:
            continue
        eyes.append((len(eye_cells), (ex0 + ex1) / 2, (ey0 + ey1) / 2))
    if len(eyes) != 2:
        return False
    (area_a, ax, ay), (area_b, bx, by) = eyes
    face_w = max(1, max_x - min_x)
    if abs(ay - by) > face_h * 0.28:
        return False
    if not face_w * 0.12 <= abs(ax - bx) <= face_w * 0.75:
        return False
    small = max(1, min(area_a, area_b))
    if max(area_a, area_b) / small > 2.6:
        return False
    return True


def _flicker_indexes(frames: list[Image.Image]) -> set[int]:
    """An isolated flash: one frame far from both neighbors, which still agree."""

    if len(frames) < 3:
        return set()
    found: set[int] = set()
    for index in range(1, len(frames) - 1):
        into = _luma_delta(frames[index - 1], frames[index])
        out = _luma_delta(frames[index], frames[index + 1])
        neighbors = _luma_delta(frames[index - 1], frames[index + 1])
        if into >= flicker_delta() and out >= flicker_delta() and neighbors <= flicker_neighbor():
            found.add(index)
    return found


def _luma_delta(left: Image.Image, right: Image.Image) -> float:
    left_buf, left_w, left_h = pack(left)
    right_buf, right_w, right_h = pack(right)
    n = 24
    total = 0
    count = 0
    for gy in range(n):
        y_left = min(left_h - 1, gy * left_h // n)
        y_right = min(right_h - 1, gy * right_h // n)
        for gx in range(n):
            x_left = min(left_w - 1, gx * left_w // n)
            x_right = min(right_w - 1, gx * right_w // n)
            total += abs(
                luma_at(left_buf, left_w, x_left, y_left)
                - luma_at(right_buf, right_w, x_right, y_right)
            )
            count += 1
    if count == 0:
        return 0.0
    return (total / count) / 255


def _face_gap(
    frames: list[Image.Image],
    anchor: Image.Image | None,
    *,
    expected_faces: int,
) -> Finding | None:
    if expected_faces <= 0:
        return None
    crops = [_face_grid(frame) for frame in frames]
    present = [item for item in crops if item is not None]
    if len(present) < 2:
        return None
    reference = _face_grid(anchor) if anchor is not None else present[0]
    if reference is None:
        reference = present[0]
    for grid in present:
        if cosine(grid, reference) < face_min_similarity():
            return Finding("face_inconsistent", "a frame face does not match the anchor")
    return None


def _face_grid(image: Image.Image | None) -> list[float] | None:
    if image is None:
        return None
    buf, width, height = pack(image)
    mask = _skin_mask(buf, width, height)
    blobs = _components(mask, width, height, minimum=max(180, width * height // 80))
    if not blobs:
        return None
    cells, _bbox = max(blobs, key=lambda item: len(item[0]))
    n = 8
    grid = [0.0] * (n * n)
    counts = [0] * (n * n)
    min_x = min(index % width for index in cells)
    max_x = max(index % width for index in cells)
    min_y = min(index // width for index in cells)
    max_y = max(index // width for index in cells)
    span_x = max(1, max_x - min_x)
    span_y = max(1, max_y - min_y)
    for index in cells:
        x = index % width
        y = index // width
        gx = min(n - 1, (x - min_x) * n // span_x)
        gy = min(n - 1, (y - min_y) * n // span_y)
        slot = gy * n + gx
        counts[slot] += 1
        grid[slot] += luma_at(buf, width, x, y) / 255
    return [grid[i] / counts[i] if counts[i] else 0.0 for i in range(n * n)]


def face_embedding(image: Image.Image) -> list[float] | None:
    """8×8 skin-luma grid. This is the face vector N11 compares at cosine 0.75."""

    return _face_grid(image)
