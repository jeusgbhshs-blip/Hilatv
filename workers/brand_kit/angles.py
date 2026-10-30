"""Side and back anchor frames. They are references, never on-screen plates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from gateway.constants import NO_RENDERED_TEXT

_PROMPTS = Path(__file__).resolve().parent / "prompts"
_ENV = Environment(
    loader=FileSystemLoader(_PROMPTS),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)
_VIEWS = ("side", "back")


class AnchorRef(BaseModel):
    """A generated angle. ``on_screen`` stays false so T13 can tell it from a cutout."""

    view: str = Field(pattern=r"^(side|back)$")
    uri: str = Field(min_length=1)
    on_screen: bool = False
    product_name: str = Field(min_length=1)


def complete_angles(
    gateway: Any,
    *,
    product_name: str,
    project_id: str,
    attempt: int,
    product_id: str,
) -> list[AnchorRef]:
    """Ask the image gateway for two anchor views. The prompt forbids drawn text."""

    refs: list[AnchorRef] = []
    for index, view in enumerate(_VIEWS):
        prompt = _ENV.get_template("angle.j2").render(
            view=view,
            product_name=product_name,
            negative=NO_RENDERED_TEXT,
        )
        if NO_RENDERED_TEXT not in prompt or "不直接上屏" not in prompt:
            raise RuntimeError("anchor prompt is missing the off-screen constraint")
        result = gateway.generate_image(
            prompt,
            seed=100 + index,
            shot_type="product",
            project_id=project_id,
            node="n02_brand_kit",
            shot_id=product_id,
            attempt=attempt,
        )
        uri = str(result.get("uri") or "")
        if not uri:
            raise RuntimeError("image gateway returned no uri")
        refs.append(AnchorRef(view=view, uri=uri, on_screen=False, product_name=product_name))
    return refs
