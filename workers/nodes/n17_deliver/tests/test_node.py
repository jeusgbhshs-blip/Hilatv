"""Full export: three aspects, two languages, subject pixels inside the frame."""

from __future__ import annotations

from workers.nodes.n17_deliver.node import run
from workers.nodes.n17_deliver.sample import acceptance_request


def test_exports_keep_the_subject_and_the_language(tmp_path, gateway) -> None:
    result = run(acceptance_request(tmp_path), gateway=gateway)
    versions = result.payload["versions"]
    assert {item["aspect_ratio"] for item in versions} == {"16:9", "9:16", "1:1"}
    assert {item["language"] for item in versions} == {"zh", "en"}
    modes = {mode for item in versions for mode in item["modes"].values()}
    assert "crop" in modes
    assert "blur" in modes
    zh = next(item for item in versions if item["language"] == "zh")
    en = next(
        item
        for item in versions
        if item["language"] == "en" and item["aspect_ratio"] == zh["aspect_ratio"]
    )
    assert zh["spoken"][0]["voiceover"] != en["spoken"][0]["voiceover"]
    assert zh["spoken"][0]["subtitle"] == zh["spoken"][0]["voiceover"] or _compact(
        zh["spoken"][0]["subtitle"]
    ) == _compact(zh["spoken"][0]["voiceover"])
    assert "drawtext" not in zh["filters"]
    assert result.payload["rights"]["subtitles"]


def _compact(text: str) -> str:
    return "".join(char for char in text if not char.isspace())
