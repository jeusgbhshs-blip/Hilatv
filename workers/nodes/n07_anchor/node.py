"""N7 anchors and product_composite.

Product photos are matted through the gateway. People come only from
``people_for_use`` / ``release_kit``. A degraded concept is recorded and is
not treated as a pass. Regenerating a scene spends the shared project budget.
"""

from __future__ import annotations

import base64
import io
import time
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from gateway.constants import NO_RENDERED_TEXT
from workers.brand_kit.angles import complete_angles
from workers.brand_kit.media_ready import ready_image_bytes
from workers.brand_kit.people import people_for_use, release_kit
from workers.brand_kit.store import (
    BrandReadError,
    append_anchors,
    read_asset,
    released_view,
    resolve_kit,
    write_asset,
)
from workers.logging import log_event
from workers.nodes.n07_anchor.composite import audit, painted_text, placement
from workers.nodes.n07_anchor.concept import classify_concept
from workers.nodes.n07_anchor.identity import (
    color_bars,
    min_view_cosine,
    views_are_copies,
    views_pass,
)
from workers.nodes.n07_anchor.qa import QAError, check
from workers.nodes.n07_anchor.schema import N7Input, NodeRequest, NodeResult
from workers.nodes.n07_anchor.sources import load_archived, load_supplied
from workers.nodes.runtime import candidate_uuid
from workers.qa.budget_store import open_project_budget, project_folder
from workers.qa.pixels import MediaLoad, resolve_project_file
from workers.qa.scores import is_quality_pass
from workers.qa.service import review_shot
from workers.schemas.asset import Candidate
from workers.schemas.brand import BrandColors, BrandKit, Person, Product
from workers.schemas.script import GenerationMode, Shot

NODE = "n07_anchor"
_PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(_PROMPTS),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)
_VIEWS = ("front", "side", "back")


class _Photo:
    def __init__(self, product_id: str, name: str, raw: bytes) -> None:
        self.product_id = product_id
        self.name = name
        self.raw = raw


class Deadline:
    def __init__(self, timeout_s: float) -> None:
        if timeout_s <= 0:
            raise TimeoutError("n07_anchor exceeded timeout")
        self._end = time.monotonic() + timeout_s

    def check(self) -> None:
        if time.monotonic() >= self._end:
            raise TimeoutError("n07_anchor exceeded timeout")


def run(
    raw: dict[str, Any],
    *,
    timeout_s: float = 120.0,
    max_attempts: int = 3,
    gateway: Any | None = None,
) -> NodeResult:
    request = NodeRequest.model_validate(raw)
    N7Input.model_validate(request.payload)
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    gateway = gateway or _default_gateway()
    last_error: QAError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = _execute(
                request,
                attempt=attempt,
                timeout_s=timeout_s,
                gateway=gateway,
            )
            check(result)
        except QAError as exc:
            last_error = exc
            log_event(
                "node_qa_failed",
                project_id=request.project_id,
                node=NODE,
                shot_id=request.shot_id,
                attempt=attempt,
                error=str(exc),
            )
            if not exc.retryable:
                raise
            continue
        return result
    raise QAError(f"n07_anchor failed after {max_attempts} attempts") from last_error


def _execute(
    request: NodeRequest,
    *,
    attempt: int,
    timeout_s: float,
    gateway: Any,
) -> NodeResult:
    deadline = Deadline(timeout_s)
    payload = N7Input.model_validate(request.payload)
    log_event(
        "node_started",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
    )
    deadline.check()
    kit, existing, from_archive = _load_kit(payload, request)
    people = _people(kit, from_archive=from_archive)
    status, passed, concept_style = classify_concept(payload.concept)
    style_source = "concept" if passed else "brief"
    style_text = concept_style if passed else _brief_style(payload)
    blocked = _blocked(payload, kit)
    style_text = _scrub(style_text, blocked) or "steady commercial light"
    budget = open_project_budget(request.project_id)
    prompts: list[str] = []
    anchors: list[dict[str, Any]] = []
    photos = _photos(payload, kit)
    cutouts: dict[str, Image.Image] = {}
    sources: dict[str, Image.Image] = {}
    for photo in photos:
        deadline.check()
        cutout, source = _cutout(
            photo,
            existing=existing,
            gateway=gateway,
            request=request,
            attempt=attempt,
            anchors=anchors,
        )
        cutouts[photo.product_id] = cutout
        sources[photo.product_id] = source
        _angles(
            photo,
            existing=existing,
            gateway=gateway,
            request=request,
            attempt=attempt,
            anchors=anchors,
            deadline=deadline,
        )
    _characters(
        people,
        gateway=gateway,
        request=request,
        attempt=attempt,
        blocked=blocked,
        prompts=prompts,
        anchors=anchors,
        deadline=deadline,
    )
    scenes = _scenes(
        payload,
        style_text=style_text,
        blocked=blocked,
        existing=existing,
        gateway=gateway,
        request=request,
        attempt=attempt,
        prompts=prompts,
        anchors=anchors,
        budget=budget,
        deadline=deadline,
    )
    _style_plate(
        kit,
        style_text=style_text,
        blocked=blocked,
        gateway=gateway,
        request=request,
        attempt=attempt,
        prompts=prompts,
        anchors=anchors,
        budget=budget,
        deadline=deadline,
    )
    candidates, reviewed = _composites(
        payload,
        request=request,
        attempt=attempt,
        gateway=gateway,
        cutouts=cutouts,
        sources=sources,
        scenes=scenes,
        photos=photos,
        anchors=anchors,
        deadline=deadline,
    )
    _publish(payload.enterprise_id, anchors)
    log_event(
        "node_finished",
        project_id=request.project_id,
        node=NODE,
        shot_id=request.shot_id,
        attempt=attempt,
        anchors=len(anchors),
        candidates=len(candidates),
    )
    return NodeResult(
        project_id=request.project_id,
        node=NODE,
        ok=True,
        payload={
            "concept_status": status,
            "concept_passed": passed,
            "style_source": style_source,
            "anchors": anchors,
            "candidates": [row.model_dump(mode="json") for row in candidates],
            "counts_as_reviewed": reviewed,
            "prompts": prompts,
            "blocked_text": blocked,
            "face_cosine_min": _face_min(anchors),
            "budget_used": budget.used,
        },
        attempt=attempt,
    )


def _load_kit(
    payload: N7Input,
    request: NodeRequest,
) -> tuple[BrandKit | None, list[dict[str, Any]], bool]:
    if payload.brand_id and not payload.enterprise_id:
        raise QAError("brand_id lookup requires enterprise_id", retryable=False)
    try:
        if payload.brand_kit is not None:
            raw = resolve_kit(
                inline=payload.brand_kit,
                brand_id=payload.brand_id,
                enterprise_id=payload.enterprise_id,
                project_id=request.project_id,
                attempt=request.attempt,
            )
            kit = BrandKit.model_validate(raw) if raw else None
            return kit, [], False
        if payload.enterprise_id:
            view = released_view(payload.enterprise_id, payload.brand_id)
            if view is None:
                return None, [], True
            return BrandKit.model_validate(view["brand_kit"]), list(view["anchors"]), True
    except BrandReadError as exc:
        raise QAError(str(exc), retryable=False) from exc
    return None, [], False


def _people(kit: BrandKit | None, *, from_archive: bool) -> list[Person]:
    if kit is None:
        return []
    released = release_kit(kit, trust_consent=from_archive)
    return people_for_use(released, trust_consent=from_archive)


def _photos(payload: N7Input, kit: BrandKit | None) -> list[_Photo]:
    found: list[_Photo] = []
    seen: set[str] = set()
    if kit is not None:
        for product in kit.products:
            raw = _product_bytes(product, payload)
            if raw is None:
                continue
            found.append(_Photo(product.product_id, product.name, raw))
            seen.add(product.product_id)
            seen.add(product.name)
    for item in payload.products:
        key = item.product_id or item.name or ""
        if not key or key in seen:
            continue
        if not item.image_b64 and not item.uri:
            continue
        raw = load_supplied(item.image_b64, item.uri, enterprise_id=payload.enterprise_id)
        found.append(_Photo(item.product_id or item.name or key, item.name or key, raw))
    return found


def _product_bytes(product: Product, payload: N7Input) -> bytes | None:
    for item in payload.products:
        if item.product_id not in {None, product.product_id} and item.name not in {
            None,
            product.name,
        }:
            continue
        if item.product_id == product.product_id or item.name == product.name:
            if item.image_b64 or item.uri:
                return load_supplied(
                    item.image_b64,
                    item.uri,
                    enterprise_id=payload.enterprise_id,
                )
    for uri in [*product.photos, *product.cutouts]:
        data = load_archived(uri, enterprise_id=payload.enterprise_id)
        if data:
            return data
    return None


def _cutout(
    photo: _Photo,
    *,
    existing: list[dict[str, Any]],
    gateway: Any,
    request: NodeRequest,
    attempt: int,
    anchors: list[dict[str, Any]],
) -> tuple[Image.Image, Image.Image]:
    source = _rgba(photo.raw).convert("RGB")
    raw = None
    cached = _find(existing, "product_cutout", product_id=photo.product_id)
    if cached is not None:
        raw = read_asset(str(cached.get("uri") or ""), enterprise_id=request_enterprise(request))
    if raw is None:
        encoded = base64.b64encode(photo.raw).decode("ascii")
        result = gateway.matte(
            "remove the flat background",
            seed=1,
            project_id=request.project_id,
            node=NODE,
            shot_id=photo.product_id,
            attempt=attempt,
            params={"image_b64": encoded},
        )
        if not result.get("edge_ok"):
            message = str(result.get("edge_message") or "抠图边缘不合格")
            if "请更换图片" not in message:
                message = f"{message}。请更换图片"
            raise QAError(message, retryable=False)
        raw = base64.b64decode(str(result["png_b64"]))
    cutout = _rgba(raw)
    if cutout.size != source.size:
        raise QAError("抠图改变了产品尺寸。请更换图片", retryable=False)
    source_path = _save(request.project_id, f"{photo.product_id}-source.png", _png(source))
    cutout_path = _save(request.project_id, f"{photo.product_id}-cutout.png", raw)
    _remember(
        anchors,
        request,
        kind="product_cutout",
        view="front",
        path=cutout_path,
        on_screen=False,
        product_id=photo.product_id,
        product_name=photo.name,
        data=raw,
    )
    _remember(
        anchors,
        request,
        kind="product_source",
        view="front",
        path=source_path,
        on_screen=False,
        product_id=photo.product_id,
        product_name=photo.name,
        data=source_path.read_bytes(),
    )
    return cutout, source


def request_enterprise(request: NodeRequest) -> str | None:
    payload = N7Input.model_validate(request.payload)
    return payload.enterprise_id


def _angles(
    photo: _Photo,
    *,
    existing: list[dict[str, Any]],
    gateway: Any,
    request: NodeRequest,
    attempt: int,
    anchors: list[dict[str, Any]],
    deadline: Deadline,
) -> None:
    missing = [
        view
        for view in ("side", "back")
        if _find(existing, "product_angle", product_id=photo.product_id, view=view) is None
    ]
    if not missing:
        for view in ("side", "back"):
            item = _find(existing, "product_angle", product_id=photo.product_id, view=view)
            assert item is not None
            data = read_asset(str(item.get("uri") or ""), enterprise_id=request_enterprise(request))
            if not data:
                missing.append(view)
                continue
            path = _save(request.project_id, f"{photo.product_id}-{view}.png", data)
            _remember(
                anchors,
                request,
                kind="product_angle",
                view=view,
                path=path,
                on_screen=False,
                product_id=photo.product_id,
                product_name=photo.name,
                data=data,
            )
        if not missing:
            return
    deadline.check()
    refs = complete_angles(
        gateway,
        product_name=photo.name,
        project_id=request.project_id,
        attempt=attempt,
        product_id=photo.product_id,
        node=NODE,
    )
    if len(refs) < 2:
        raise QAError("产品多角度参考没有生成", retryable=True)
    for ref in refs:
        data = ready_image_bytes(gateway, ref.uri)
        if data is None:
            raise QAError("产品多角度参考没有可读的像素", retryable=True)
        path = _save(request.project_id, f"{photo.product_id}-{ref.view}.png", data)
        _remember(
            anchors,
            request,
            kind="product_angle",
            view=ref.view,
            path=path,
            on_screen=False,
            product_id=photo.product_id,
            product_name=photo.name,
            data=data,
        )


def _characters(
    people: list[Person],
    *,
    gateway: Any,
    request: NodeRequest,
    attempt: int,
    blocked: list[str],
    prompts: list[str],
    anchors: list[dict[str, Any]],
    deadline: Deadline,
) -> None:
    for person in people:
        deadline.check()
        plates: dict[str, Image.Image] = {}
        for index, view in enumerate(_VIEWS):
            prompt = _render(
                "character.j2",
                view=view,
                role=_scrub(person.role, blocked) or "person",
                negative=NO_RENDERED_TEXT,
            )
            prompts.append(prompt)
            data = _generate(
                gateway,
                prompt,
                seed=40 + index,
                shot_type="person",
                request=request,
                shot_id=person.person_id,
                attempt=attempt,
            )
            plates[view] = _rgb(data)
        if (
            not views_pass(plates)
            or views_are_copies(plates)
            or any(painted_text(image) for image in plates.values())
        ):
            raise QAError(
                "人物三视图未通过人脸相似度，需要人工确认",
                retryable=False,
                needs_human=True,
            )
        for view, image in plates.items():
            path = _save(request.project_id, f"{person.person_id}-{view}.png", _png(image))
            _remember(
                anchors,
                request,
                kind="character",
                view=view,
                path=path,
                on_screen=False,
                person_id=person.person_id,
                product_name=person.role,
                data=path.read_bytes(),
            )
        sheet_prompt = _render(
            "character.j2",
            view="expressions",
            role=_scrub(person.role, blocked) or "person",
            negative=NO_RENDERED_TEXT,
        )
        prompts.append(sheet_prompt)
        sheet = _rgb(
            _generate(
                gateway,
                sheet_prompt,
                seed=43,
                shot_type="person",
                request=request,
                shot_id=person.person_id,
                attempt=attempt,
            )
        )
        if painted_text(sheet):
            raise QAError("表情表有文字乱码，需要人工确认", retryable=False, needs_human=True)
        path = _save(request.project_id, f"{person.person_id}-expressions.png", _png(sheet))
        _remember(
            anchors,
            request,
            kind="character",
            view="expressions",
            path=path,
            on_screen=False,
            person_id=person.person_id,
            product_name=person.role,
            data=path.read_bytes(),
        )


def _scenes(
    payload: N7Input,
    *,
    style_text: str,
    blocked: list[str],
    existing: list[dict[str, Any]],
    gateway: Any,
    request: NodeRequest,
    attempt: int,
    prompts: list[str],
    anchors: list[dict[str, Any]],
    budget: Any,
    deadline: Deadline,
) -> dict[str, Image.Image]:
    found: dict[str, Image.Image] = {}
    for ref in _scene_refs(payload):
        deadline.check()
        cached = _find(existing, "scene", scene_ref=ref)
        if cached is not None:
            data = read_asset(str(cached.get("uri") or ""), enterprise_id=payload.enterprise_id)
            if data and painted_text(_rgb(data)) is None:
                image = _rgb(data)
                path = _save(request.project_id, f"scene-{ref}.png", _png(image))
                _remember(
                    anchors,
                    request,
                    kind="scene",
                    view="",
                    path=path,
                    on_screen=False,
                    scene_ref=ref,
                    data=path.read_bytes(),
                )
                found[ref] = Image.open(path)
                found[ref].load()
                continue
        image, prompt = _clean_scene(
            ref,
            style_text=style_text,
            blocked=blocked,
            gateway=gateway,
            request=request,
            attempt=attempt,
            prompts=prompts,
            budget=budget,
        )
        path = _save(request.project_id, f"scene-{ref}.png", _png(image))
        _remember(
            anchors,
            request,
            kind="scene",
            view="",
            path=path,
            on_screen=False,
            scene_ref=ref,
            prompt=prompt,
            data=path.read_bytes(),
        )
        found[ref] = Image.open(path)
        found[ref].load()
    return found


def _clean_scene(
    ref: str,
    *,
    style_text: str,
    blocked: list[str],
    gateway: Any,
    request: NodeRequest,
    attempt: int,
    prompts: list[str],
    budget: Any,
) -> tuple[Image.Image, str]:
    last = "乱码"
    seed = 7
    while True:
        prompt = _render(
            "scene.j2",
            scene_ref=_scrub(ref, blocked) or "set",
            style=style_text,
            negative=NO_RENDERED_TEXT,
        )
        data = _generate(
            gateway,
            prompt,
            seed=seed,
            shot_type="scene",
            request=request,
            shot_id=ref,
            attempt=attempt,
        )
        image = _rgb(data)
        detail = painted_text(image)
        if detail is None:
            prompts.append(prompt)
            return image, prompt
        last = detail
        if not budget.try_take():
            break
        seed += 1
    raise QAError(f"场景图有文字乱码，项目重生次数已到上限。{last}", retryable=False)


def _style_plate(
    kit: BrandKit | None,
    *,
    style_text: str,
    blocked: list[str],
    gateway: Any,
    request: NodeRequest,
    attempt: int,
    prompts: list[str],
    anchors: list[dict[str, Any]],
    budget: Any,
    deadline: Deadline,
) -> None:
    deadline.check()
    prompt = _render(
        "style.j2",
        style=_scrub(style_text, blocked),
        negative=NO_RENDERED_TEXT,
    )
    prompts.append(prompt)
    data = _generate(
        gateway,
        prompt,
        seed=3,
        shot_type="style",
        request=request,
        shot_id="style",
        attempt=attempt,
    )
    mood = _rgb(data)
    if painted_text(mood) and budget.try_take():
        data = _generate(
            gateway,
            prompt,
            seed=4,
            shot_type="style",
            request=request,
            shot_id="style",
            attempt=attempt,
        )
        mood = _rgb(data)
    if painted_text(mood) is None:
        path = _save(request.project_id, "style-mood.png", _png(mood))
        _remember(
            anchors,
            request,
            kind="style",
            view="mood",
            path=path,
            on_screen=False,
            data=path.read_bytes(),
        )
    if kit is None:
        colors = BrandColors(primary="#0A3D91", secondary="#FFFFFF", accent="#F5A623")
    else:
        colors = kit.colors
    bars = color_bars(colors)
    if painted_text(bars):
        raise QAError("场景图有文字乱码", retryable=False)
    path = _save(request.project_id, "style-bars.png", _png(bars))
    _remember(
        anchors,
        request,
        kind="style",
        view="bars",
        path=path,
        on_screen=False,
        data=path.read_bytes(),
    )


def _composites(
    payload: N7Input,
    *,
    request: NodeRequest,
    attempt: int,
    gateway: Any,
    cutouts: dict[str, Image.Image],
    sources: dict[str, Image.Image],
    scenes: dict[str, Image.Image],
    photos: list[_Photo],
    anchors: list[dict[str, Any]],
    deadline: Deadline,
) -> tuple[list[Candidate], dict[str, bool]]:
    rows: list[Candidate] = []
    reviewed: dict[str, bool] = {}
    if payload.script is None:
        return rows, reviewed
    for shot in payload.script.shots:
        if request.shot_id and shot.shot_id != request.shot_id:
            continue
        if shot.generation_mode is not GenerationMode.product_composite:
            continue
        deadline.check()
        photo = _match(shot, photos)
        if photo is None or photo.product_id not in cutouts:
            raise QAError("产品合成缺少可用的产品图。请更换图片", retryable=False)
        scene = scenes.get(shot.scene_ref)
        if scene is None:
            raise QAError("产品合成缺少场景锚点", retryable=False)
        cutout = cutouts[photo.product_id]
        original = sources[photo.product_id]
        try:
            x, y, quad = placement(scene.size, cutout.size)
        except ValueError as exc:
            raise QAError("产品图放不进场景。请更换图片", retryable=False) from exc
        scene_path = _path_of(anchors, "scene", scene_ref=shot.scene_ref)
        cutout_path = _path_of(anchors, "product_cutout", product_id=photo.product_id)
        source_path = _path_of(anchors, "product_source", product_id=photo.product_id)
        result = gateway.relight(
            "relight the set around the product",
            seed=5,
            project_id=request.project_id,
            node=NODE,
            shot_id=shot.shot_id,
            attempt=attempt,
            params={
                "image_b64": base64.b64encode(scene_path.read_bytes()).decode("ascii"),
                "cutout_b64": base64.b64encode(cutout_path.read_bytes()).decode("ascii"),
                "x": x,
                "y": y,
            },
        )
        encoded = str(result.get("png_b64") or "")
        if not encoded:
            message = str(result.get("edge_message") or "重打光失败。请更换图片")
            raise QAError(message, retryable=False)
        composite_path = _save(
            request.project_id,
            f"{shot.shot_id}-composite.png",
            base64.b64decode(encoded),
        )
        composite = Image.open(composite_path)
        composite.load()
        checked = audit(
            composite,
            Image.open(scene_path),
            Image.open(cutout_path),
            original,
            (x, y),
            quad,
        )
        report = review_shot(
            {
                "project_id": request.project_id,
                "shot_id": shot.shot_id,
                "node": NODE,
                "candidate_uri": str(composite_path),
                "purpose": shot.purpose,
                "visual": shot.visual,
                "generation_mode": shot.generation_mode.value,
            },
            gateway=gateway,
        )
        selected = bool(report.visual_reviewed and is_quality_pass(report))
        prompt = next((item for item in anchors if item.get("scene_ref") == shot.scene_ref), {})
        rows.append(
            Candidate(
                candidate_id=candidate_uuid(
                    request.project_id,
                    shot.shot_id,
                    "N7",
                    "product_composite",
                    attempt,
                ),
                shot_id=shot.shot_id,
                node="N7",
                model=str(result.get("interface") or "ic-light-local"),
                params={
                    "prompt": _scene_prompt(anchors, shot.scene_ref),
                    "seed": attempt,
                    "mode": "product_composite",
                    "x": x,
                    "y": y,
                    "quad": quad,
                    "scene_path": str(scene_path),
                    "cutout_path": str(cutout_path),
                    "source_path": str(source_path),
                    "deformation": checked.deformation,
                    "pixel_matches": checked.pixel_matches,
                    "visual_reviewed": report.visual_reviewed,
                },
                uri=str(composite_path),
                qa=report,
                selected=selected,
            )
        )
        reviewed[shot.shot_id] = report.visual_reviewed
        _remember(
            anchors,
            request,
            kind="product_composite",
            view="front",
            path=composite_path,
            on_screen=True,
            product_id=photo.product_id,
            product_name=photo.name,
            scene_ref=shot.scene_ref,
            shot_id=shot.shot_id,
            data=composite_path.read_bytes(),
        )
        del prompt
    return rows, reviewed


def _scene_prompt(anchors: list[dict[str, Any]], scene_ref: str) -> str:
    for item in anchors:
        if item.get("kind") == "scene" and item.get("scene_ref") == scene_ref:
            text = str(item.get("prompt") or "")
            if text:
                return text
    return NO_RENDERED_TEXT


def _match(shot: Shot, photos: list[_Photo]) -> _Photo | None:
    refs = [ref for ref in shot.subject_refs if ref.startswith("product:")] or shot.subject_refs
    for ref in refs:
        token = ref.split(":", 1)[1] if ":" in ref else ref
        for photo in photos:
            if token in {photo.product_id, photo.name} or photo.name.endswith(token):
                return photo
    return photos[0] if len(photos) == 1 else None


def _scene_refs(payload: N7Input) -> list[str]:
    refs: list[str] = []
    if payload.script is not None:
        for shot in payload.script.shots:
            if shot.scene_ref and shot.scene_ref not in refs:
                refs.append(shot.scene_ref)
    return refs or ["default"]


def _brief_style(payload: N7Input) -> str:
    if payload.brief is not None and payload.brief.style:
        return payload.brief.style
    return "steady commercial light"


def _blocked(payload: N7Input, kit: BrandKit | None) -> list[str]:
    blocked: list[str] = []
    if kit is not None:
        for value in (kit.cta.phone, kit.cta.website, kit.cta.wechat_qr):
            if value:
                blocked.append(value)
    if payload.script is not None:
        for shot in payload.script.shots:
            for card in shot.on_screen_text:
                if card.text:
                    blocked.append(card.text)
    return blocked


def _scrub(text: str, blocked: list[str]) -> str:
    cleaned = text
    for item in blocked:
        if item:
            cleaned = cleaned.replace(item, " ")
    return " ".join(cleaned.split())


def _render(name: str, **kwargs: object) -> str:
    text = _ENV.get_template(name).render(**kwargs).strip()
    if NO_RENDERED_TEXT not in text:
        text = f"{text}\n{NO_RENDERED_TEXT}"
    return text


def _generate(
    gateway: Any,
    prompt: str,
    *,
    seed: int,
    shot_type: str,
    request: NodeRequest,
    shot_id: str,
    attempt: int,
) -> bytes:
    result = gateway.generate_image(
        prompt,
        seed=seed,
        shot_type=shot_type,
        project_id=request.project_id,
        node=NODE,
        shot_id=shot_id,
        attempt=attempt,
    )
    data = ready_image_bytes(gateway, str(result.get("uri") or ""))
    if data is None:
        raise QAError("锚点图没有可读的像素", retryable=True)
    return data


def _find(
    existing: list[dict[str, Any]],
    kind: str,
    **fields: str,
) -> dict[str, Any] | None:
    for item in existing:
        if item.get("kind") != kind:
            continue
        if all(item.get(key) == value for key, value in fields.items()):
            return item
    return None


def _remember(
    anchors: list[dict[str, Any]],
    request: NodeRequest,
    *,
    kind: str,
    view: str,
    path: Path,
    on_screen: bool,
    data: bytes,
    product_id: str = "",
    product_name: str = "",
    person_id: str = "",
    scene_ref: str = "",
    shot_id: str = "",
    prompt: str = "",
) -> None:
    enterprise_id = request_enterprise(request)
    uri = str(path)
    if enterprise_id:
        try:
            uri = write_asset(enterprise_id, _safe(path.name), data)
        except BrandReadError:
            uri = str(path)
    anchors.append(
        {
            "kind": kind,
            "view": view,
            "uri": uri,
            "path": str(path),
            "on_screen": on_screen,
            "product_id": product_id,
            "product_name": product_name,
            "person_id": person_id,
            "scene_ref": scene_ref,
            "shot_id": shot_id,
            "prompt": prompt,
        }
    )


def _publish(enterprise_id: str | None, anchors: list[dict[str, Any]]) -> None:
    if not enterprise_id:
        return
    append_anchors(enterprise_id, anchors)


def _path_of(anchors: list[dict[str, Any]], kind: str, **fields: str) -> Path:
    for item in anchors:
        if item.get("kind") != kind:
            continue
        if all(item.get(key) == value for key, value in fields.items()):
            return Path(str(item["path"]))
    raise QAError(f"missing {kind} file", retryable=False)


def _save(project_id: str, name: str, data: bytes) -> Path:
    folder = (project_folder(project_id) / "anchors").resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = (folder / _safe(name)).resolve()
    try:
        path.relative_to(folder)
    except ValueError as exc:
        raise QAError("asset path is outside the project directory", retryable=False) from exc
    path.write_bytes(data)
    located = resolve_project_file(path)
    if isinstance(located, MediaLoad):
        raise QAError(located.reason, retryable=False)
    return located


def _safe(name: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in name)
    if not cleaned.endswith(".png"):
        cleaned = f"{cleaned}.png"
    return cleaned[:120] or "asset.png"


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _rgb(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGB")


def _rgba(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGBA")


def _face_min(anchors: list[dict[str, Any]]) -> float | None:
    grouped: dict[str, dict[str, Image.Image]] = {}
    for item in anchors:
        if item.get("kind") != "character" or item.get("view") not in _VIEWS:
            continue
        grouped.setdefault(str(item.get("person_id") or ""), {})[str(item["view"])] = Image.open(
            item["path"]
        )
    scores = [min_view_cosine(views) for views in grouped.values() if len(views) == 3]
    if not scores:
        return None
    return min(scores)


def _default_gateway() -> Any:
    from gateway import get_gateway

    return get_gateway()
