"""Canvas exposes saved choices, including normalized legacy automatic fields."""

import pytest

from workers.expert.canvas import build_canvas
from workers.workflow.store import init_project, read_snapshot


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({}, {"aspect_ratio": None, "duration_s": None}),
        ({"generation_settings": {"duration_s": 30}}, {"aspect_ratio": None, "duration_s": 30}),
        (
            {"generation_settings": {"aspect_ratio": "21:9", "duration_s": 180}},
            {"aspect_ratio": "21:9", "duration_s": 180},
        ),
    ],
)
def test_canvas_settings_are_public_normalized_and_read_only(
    tmp_path, monkeypatch, fields, expected
):
    monkeypatch.setenv("HILATV_PROJECT_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("HILATV_LIVE", "0")
    init_project("settings-canvas", status="draft", draft_revision=2, **fields)
    before = read_snapshot("settings-canvas")
    canvas = build_canvas("settings-canvas")
    assert canvas["draft_revision"] == 2
    assert canvas["generation_settings"] == expected
    assert read_snapshot("settings-canvas") == before
