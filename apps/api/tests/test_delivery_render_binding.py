"""Export follows the actual rendered cut map and the confirmed target clock."""

import copy

import pytest

from app import deliveries
from workers.nodes.n17_deliver.sample import acceptance_request


@pytest.mark.parametrize("source", ["rendered", "aligned", "legacy"])
@pytest.mark.parametrize("archived_clock", [True, False])
def test_export_uses_the_picture_cut_script_and_never_relabels_measured_time(
    tmp_path, monkeypatch, source, archived_clock
):
    request = acceptance_request(tmp_path / "assets", aspect_ratios=["16:9"], languages=["zh"])
    payload = request["payload"]
    original = copy.deepcopy(payload["script"])
    aligned = copy.deepcopy(original)
    aligned["shots"][0]["duration_s"] += 0.2
    aligned["shots"][1]["duration_s"] -= 0.2
    rendered = copy.deepcopy(aligned)
    rendered["shots"][0]["duration_s"] += 0.1
    rendered["shots"][1]["duration_s"] -= 0.1
    saved = {
        "brief": payload["brief"],
        "script": original,
        "timeline": {"duration_s": 18.4, "target_duration_s": 15},
    }
    if archived_clock:
        saved["production_clock"] = {"target_duration_s": 15, "intro_s": 0, "outro_s": 2.4}
    if source in {"rendered", "aligned"}:
        saved["aligned_script"] = aligned
    if source == "rendered":
        saved["rendered_script"] = rendered
    monkeypatch.setattr(deliveries, "_checkpoint", lambda _id: saved)
    monkeypatch.setattr(deliveries, "_master_in_project", lambda *_args: payload["master_path"])
    monkeypatch.setattr(deliveries, "project_path", lambda _id: tmp_path)
    snapshot = {"generation_settings": {"aspect_ratio": "4:3", "duration_s": None}}
    body = deliveries.DeliverBody(aspect_ratios=["4:3"], languages=["zh"])
    actual = deliveries._payload("export-clock", snapshot, body)
    expected = {"rendered": rendered, "aligned": aligned, "legacy": original}[source]
    assert actual["script"] == expected
    assert actual["source_timeline"] == saved["timeline"]
    assert actual["target_duration_s"] == 15
    # An explicit script is still subject to N17's source mapping checks, rather
    # than being silently swapped for the server default.
    explicit = deliveries._payload(
        "export-clock", snapshot, deliveries.DeliverBody(script=original)
    )
    assert explicit["script"] == original


def test_public_export_keeps_source_identity_without_exposing_source_paths():
    item = {
        "version_id": "v1",
        "aspect_ratio": "4:3",
        "language": "zh",
        "duration_s": 15,
        "width": 960,
        "height": 720,
        "modes": [],
        "source_key": "source-hash",
        "source_media_hash": "actual-clean-hash",
        "path": "/private/clip.mp4",
    }
    public = deliveries._public("project", item)
    assert public["source_key"] == "source-hash"
    assert public["source_media_hash"] == "actual-clean-hash"
    assert "/private/" not in str(public)
