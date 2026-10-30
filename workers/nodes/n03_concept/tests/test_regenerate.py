"""Similarity over 0.85 regenerates. A mock image never counts as a cover."""

from __future__ import annotations

from gateway.storage import MemoryObjectStore
from workers.brand_kit.tests.images import logo_png
from workers.nodes.n03_concept.node import _TEXT_ATTEMPTS, run
from workers.nodes.n03_concept.tests.test_node import _BRIEF

_SAME = "同一句完全相同的文案用来测相似度同一句完全相同的文案"


def _card(index: int, idea: str) -> dict:
    return {
        "direction_id": f"d{index}",
        "title": f"标题{index}",
        "idea": idea,
        "mood": f"情绪{index}",
        "structure": ["钩子", "卖点", "证明", "行动"],
        "style_keywords": [f"词{index}"],
        "estimated_effect": f"效果{index}{idea[:8]}",
    }


def _draft(ideas: list[str]) -> dict:
    return {"directions": [_card(index, idea) for index, idea in enumerate(ideas, start=1)]}


class Scripted:
    def __init__(self, drafts: list[dict], *, store: MemoryObjectStore | None = None) -> None:
        self.drafts = list(drafts)
        self.calls = 0
        self.image_calls = 0
        self.store = store
        self.registry = {"mock": self} if store is not None else {}

    def generate_text(self, prompt: str, **kwargs: object) -> dict:
        self.calls += 1
        if self.drafts:
            return self.drafts.pop(0)
        return {"directions": []}

    def generate_image(self, prompt: str, **kwargs: object) -> dict:
        self.image_calls += 1
        if self.store is None:
            return {"uri": "mock://cover"}
        uri = self.store.put(f"cover-{self.image_calls}.png", logo_png(), "image/png")
        return {"uri": uri}


def test_similar_draft_is_regenerated_then_accepted() -> None:
    distinct = [
        "开场只谈产线停摆，中段交给可核对的工况。",
        "片子由装配现场进入，随后出现检测台，停在联系。",
        "观众先记住质检，中间用设备运转作证，结尾落到外观。",
    ]
    gateway = Scripted([_draft([_SAME, _SAME, _SAME]), _draft(distinct)])
    result = run(
        {"project_id": "regen", "payload": {"brief": _BRIEF}},
        gateway=gateway,
        max_attempts=1,
    )
    assert gateway.calls >= 2
    concept = result.payload["concept"]
    assert concept["text_source"] == "model"
    assert all(item["source"] == "model" for item in concept["directions"])
    assert result.ok is False
    assert concept["degraded"] is True
    assert all(item["cover_status"] == "not_ready" for item in concept["directions"])
    assert all(not item["cover_uri"].startswith("mock:") for item in concept["directions"])


def test_similarity_cap_falls_back_to_marked_templates() -> None:
    gateway = Scripted([_draft([_SAME, _SAME, _SAME])] * _TEXT_ATTEMPTS)
    result = run(
        {"project_id": "degraded", "payload": {"brief": _BRIEF}},
        gateway=gateway,
        max_attempts=1,
    )
    assert gateway.calls == _TEXT_ATTEMPTS
    concept = result.payload["concept"]
    assert result.ok is False
    assert concept["degraded"] is True
    assert concept["text_source"] == "template_fallback"
    assert all(item["source"] == "template_fallback" for item in concept["directions"])


def test_readable_cover_can_pass_after_a_distinct_draft() -> None:
    distinct = [
        "开场只谈产线停摆，中段交给可核对的工况。",
        "片子由装配现场进入，随后出现检测台，停在联系。",
        "观众先记住质检，中间用设备运转作证，结尾落到外观。",
    ]
    gateway = Scripted([_draft(distinct)], store=MemoryObjectStore())
    result = run(
        {"project_id": "ready", "payload": {"brief": _BRIEF}},
        gateway=gateway,
        max_attempts=1,
    )
    assert result.ok is True
    concept = result.payload["concept"]
    assert concept["degraded"] is False
    assert all(item["cover_status"] == "ready" for item in concept["directions"])
    previews = [item["cover_preview"] for item in concept["directions"]]
    assert all(item.startswith("data:image/png;base64,") for item in previews)
    assert all(not item["cover_uri"].startswith("mock:") for item in concept["directions"])
