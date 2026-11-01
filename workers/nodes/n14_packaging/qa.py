"""Quality check for N14. The closing card always carries a logo and a CTA."""

from __future__ import annotations

from workers.media.packaging import ai_label_text, intro_spec
from workers.nodes.n14_packaging.schema import NodeResult, PackageElement
from workers.schemas.asset import Asset, AssetKind
from workers.schemas.script import Script


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> list[PackageElement]:
    if result.node != "n14_packaging":
        raise QAError(f"unexpected node {result.node}")
    if not result.ok:
        raise QAError("n14_packaging result is not ok")
    script = Script.model_validate(result.payload.get("script"))
    raw_elements = result.payload.get("elements") or []
    elements = [PackageElement.model_validate(item) for item in raw_elements]
    assets = [Asset.model_validate(item) for item in result.payload.get("assets") or []]
    template = str(result.payload.get("intro_template") or "")
    allowed = set(intro_spec()["templates"]) | {"none"}
    if template not in allowed:
        raise QAError(f"unknown intro template {template}")
    intro_s = float(result.payload.get("intro_s") or 0)
    if template == "none":
        if intro_s != 0:
            raise QAError("an omitted intro still takes time")
        if any(item.kind == "intro_logo" for item in elements):
            raise QAError("omitted intro still has a logo card")
    else:
        if not 0 < intro_s <= float(intro_spec()["max_s"]) + 1e-6:
            raise QAError(f"intro is {intro_s}s, the limit is 2s")
        if not any(item.kind == "intro_logo" and item.template == template for item in elements):
            raise QAError("intro logo is missing")
    logos = [item for item in elements if item.kind == "outro_logo"]
    ctas = [item for item in elements if item.kind == "outro_cta"]
    show_logo = result.payload.get("brand_logo", True) is not False
    logo_status = str(result.payload.get("logo_status") or "unknown")
    expects_logo = logo_status not in {"missing", "mock"}
    if len(logos) != int(expects_logo) or len(ctas) != 1:
        raise QAError("the ending needs one logo and one CTA")
    if not expects_logo and any("logo" in item.kind for item in elements):
        raise QAError("a missing or simulated brand must not draw a replacement logo")
    if not show_logo and any(item.kind in {"intro_logo", "corner_logo"} for item in elements):
        raise QAError("corner and opening logos were supposed to be omitted")
    phone = str(result.payload.get("phone") or "")
    if phone and phone not in ctas[0].text:
        raise QAError("CTA does not include the brand phone")
    if not ctas[0].text.strip():
        raise QAError("CTA text is empty")
    labels = [item for item in elements if item.kind == "ai_label"]
    if len(labels) != 1 or labels[0].text != ai_label_text():
        raise QAError("AI label placeholder is missing")
    badges = [item.text for item in elements if item.kind == "badge"]
    expected = [card.text for shot in script.shots for card in shot.on_screen_text]
    if badges != expected:
        raise QAError("badges must be the on-screen cards, in order")
    if expects_logo and not any(item.kind is AssetKind.logo for item in assets):
        raise QAError("logo asset is missing")
    for item in elements:
        if item.end_s + 1e-3 < item.start_s:
            raise QAError(f"{item.element_id} ends before it starts")
        if not item.png_path:
            raise QAError(f"{item.element_id} has no PNG")
    corner = bool(result.payload.get("corner_logo"))
    has_corner = any(item.kind == "corner_logo" for item in elements)
    if corner != has_corner:
        raise QAError("corner logo flag does not match the elements")
    return elements
