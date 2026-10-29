from gateway.constants import NO_RENDERED_TEXT
from workers.nodes.n08_keyframe.prompts import render_keyframe


def test_each_model_template_forbids_rendered_text_and_differs() -> None:
    shared = {
        "camera": "The camera eases forward.",
        "subject": "An unmarked pump on a bench.",
        "scene": "Scene workshop, same light.",
        "style": "Cool industrial light.",
        "negative": NO_RENDERED_TEXT,
    }
    seedream = render_keyframe(model="doubao-seedream-4-0-250828", **shared)
    kling = render_keyframe(model="kling-image-v1", **shared)
    generic = render_keyframe(model="mock-image", **shared)
    assert seedream != kling != generic
    assert seedream.startswith("Photographic still")
    assert kling.startswith("Subject-first frame")
    assert generic.startswith("Generic still")
    for text in (seedream, kling, generic):
        assert NO_RENDERED_TEXT in text
        assert "30 MPa" not in text
