"""Re-check N7 pixels, face cosine, scenes, and the concept gate."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from gateway.constants import NO_RENDERED_TEXT
from workers.nodes.n07_anchor.composite import audit, painted_text, placement
from workers.nodes.n07_anchor.identity import min_view_cosine
from workers.nodes.n07_anchor.schema import NodeResult
from workers.qa.pixels import MediaLoad, resolve_project_file
from workers.qa.scores import is_quality_pass
from workers.qa.settings import face_min_similarity
from workers.schemas.asset import Candidate


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> dict[str, object]:
    if result.node != "n07_anchor":
        raise QAError("n07_anchor result is not ok", retryable=False)
    payload = result.payload
    _concept(payload)
    _prompts(payload)
    _angles(payload)
    if not result.ok:
        raise QAError("n07_anchor result is not ok", retryable=False)
    _scenes(payload)
    _faces(payload)
    _composites(payload)
    return payload


def _concept(payload: dict[str, object]) -> None:
    status = str(payload.get("concept_status") or "")
    passed = payload.get("concept_passed") is True
    if status != "passed" and passed:
        raise QAError("degraded concept cannot pass", retryable=False)
    if status == "degraded" and payload.get("style_source") == "concept":
        raise QAError("degraded concept was used as the style", retryable=False)


def _prompts(payload: dict[str, object]) -> None:
    prompts = payload.get("prompts")
    if not isinstance(prompts, list):
        raise QAError("prompts must be a list", retryable=False)
    blocked = payload.get("blocked_text")
    banned: list[str] = []
    if isinstance(blocked, list):
        banned = [item for item in blocked if isinstance(item, str) and item]
    for prompt in prompts:
        if not isinstance(prompt, str) or NO_RENDERED_TEXT not in prompt:
            raise QAError("prompt is missing the no-text constraint", retryable=False)
        for item in banned:
            if item in prompt:
                raise QAError("prompt contains on-screen text", retryable=False)


def _angles(payload: dict[str, object]) -> None:
    anchors = payload.get("anchors")
    if not isinstance(anchors, list):
        raise QAError("anchors must be a list", retryable=False)
    for item in anchors:
        if not isinstance(item, dict):
            raise QAError("anchor must be an object", retryable=False)
        if item.get("kind") == "product_angle" and item.get("on_screen") is not False:
            raise QAError("多角度补全不能直接上屏", retryable=False)


def _scenes(payload: dict[str, object]) -> None:
    anchors = payload.get("anchors")
    assert isinstance(anchors, list)
    for item in anchors:
        if not isinstance(item, dict) or item.get("kind") not in {"scene", "style"}:
            continue
        image = _open(str(item.get("path") or item.get("uri") or ""))
        if painted_text(image):
            raise QAError("场景图有文字乱码", retryable=False)


def _faces(payload: dict[str, object]) -> None:
    anchors = payload.get("anchors")
    assert isinstance(anchors, list)
    grouped: dict[str, dict[str, Image.Image]] = {}
    for item in anchors:
        if not isinstance(item, dict) or item.get("kind") != "character":
            continue
        view = str(item.get("view") or "")
        if view not in {"front", "side", "back"}:
            continue
        person_id = str(item.get("person_id") or "")
        grouped.setdefault(person_id, {})[view] = _open(str(item.get("path") or ""))
    threshold = face_min_similarity()
    for views in grouped.values():
        if set(views) != {"front", "side", "back"}:
            raise QAError("人物锚点缺少三视图", retryable=False)
        if min_view_cosine(views) < threshold:
            raise QAError("人物三视图人脸相似度低于 0.75", retryable=False)
        blobs = [image.tobytes() for image in views.values()]
        if len(set(blobs)) < 3:
            raise QAError("三视图不能是同一张图", retryable=False)


def _composites(payload: dict[str, object]) -> None:
    raw_rows = payload.get("candidates")
    if not isinstance(raw_rows, list):
        raise QAError("candidates must be a list", retryable=False)
    reviewed = payload.get("counts_as_reviewed")
    if not isinstance(reviewed, dict):
        raise QAError("counts_as_reviewed must be an object", retryable=False)
    for item in raw_rows:
        row = Candidate.model_validate(item)
        if row.selected and not row.qa.visual_reviewed:
            raise QAError("unreviewed composite was selected", retryable=False)
        if reviewed.get(row.shot_id) is not row.qa.visual_reviewed:
            raise QAError("reviewed flag does not match the QA report", retryable=False)
        if row.qa.visual_reviewed and not is_quality_pass(row.qa) and row.selected:
            raise QAError("unreviewed composite was selected", retryable=False)
        if row.selected and not is_quality_pass(row.qa):
            raise QAError("selected composite did not pass review", retryable=False)
        composite = _open(row.uri)
        scene = _open(str(row.params.get("scene_path") or ""))
        cutout = _open_rgba(str(row.params.get("cutout_path") or ""))
        original = _open(str(row.params.get("source_path") or ""))
        if Path(row.uri).resolve() == Path(str(row.params.get("source_path"))).resolve():
            raise QAError("product check compared a file to itself", retryable=False)
        origin = (int(row.params["x"]), int(row.params["y"]))
        x, y, quad = placement(scene.size, cutout.size)
        if (x, y) != origin:
            raise QAError("composite origin does not match the scene", retryable=False)
        try:
            audit(composite, scene, cutout, original, origin, quad)
        except ValueError as exc:
            raise QAError(str(exc), retryable=False) from exc


def _open(uri: str) -> Image.Image:
    located = _locate(uri)
    image = Image.open(located)
    image.load()
    return image.convert("RGB")


def _open_rgba(uri: str) -> Image.Image:
    located = _locate(uri)
    image = Image.open(located)
    image.load()
    return image.convert("RGBA")


def _locate(uri: str) -> Path:
    if uri.startswith("brand://"):
        raise QAError("qa reads project files, not brand uris", retryable=False)
    located = resolve_project_file(Path(uri))
    if isinstance(located, MediaLoad):
        raise QAError(located.reason, retryable=False)
    return located
