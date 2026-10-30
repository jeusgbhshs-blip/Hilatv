"""Quality check for N2. A bad cutout asks for a new picture and is not retried."""

from __future__ import annotations

from workers.nodes.n02_brand_kit.schema import NodeResult
from workers.schemas.brand import BrandKit


class QAError(Exception):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def check(result: NodeResult) -> BrandKit | None:
    if result.node != "n02_brand_kit" or not result.ok:
        raise QAError("n02_brand_kit result is not ok", retryable=False)
    raw = result.payload.get("brand_kit")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise QAError("brand_kit must be an object", retryable=False)
    try:
        kit = BrandKit.model_validate(raw)
    except Exception as exc:
        raise QAError(f"brand kit failed validation: {exc}", retryable=False) from exc
    for person in kit.people:
        if person.consent is not True:
            raise QAError("未勾选肖像授权的人物不可被使用", retryable=False)
    for person_id in result.payload.get("usable_people") or []:
        match = next((person for person in kit.people if person.person_id == person_id), None)
        if match is None or match.consent is not True:
            raise QAError("未勾选肖像授权的人物不可被使用", retryable=False)
    for anchor in result.payload.get("anchors") or []:
        if anchor.get("on_screen") is not False:
            raise QAError("多角度补全不能直接上屏", retryable=False)
        uri = str(anchor.get("uri") or "")
        for product in kit.products:
            if uri and (uri in product.photos or uri in product.cutouts):
                raise QAError("锚点参考图写进了上屏素材", retryable=False)
    return kit
