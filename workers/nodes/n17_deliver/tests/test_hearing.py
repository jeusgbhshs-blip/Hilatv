"""Hearing QA: a mock echo is not a pass, a live transcript is."""

from __future__ import annotations

import pytest

from workers.nodes.n17_deliver.qa import QAError, _language
from workers.nodes.n17_deliver.schema import DeliveryVersion, SpokenLine


def test_mock_hearing_checks_subtitle_language_only() -> None:
    version = _version(
        spoken=[
            SpokenLine(
                shot_id="S01",
                voiceover="先看这台柱塞泵",
                subtitle="先看这台柱塞泵",
            )
        ]
    )
    _language(version)


def test_verified_hearing_compares_subtitle_to_transcript() -> None:
    version = _version(
        spoken=[
            SpokenLine(
                shot_id="S01",
                voiceover="先看这台柱塞泵",
                subtitle="先看这台柱塞泵",
                transcript="先看这台柱塞泵",
                heard_check="verified",
            )
        ]
    )
    _language(version)
    mismatched = version.model_copy(
        update={
            "spoken": [
                SpokenLine(
                    shot_id="S01",
                    voiceover="先看这台柱塞泵",
                    subtitle="先看这台柱塞泵",
                    transcript="别的句子",
                    heard_check="verified",
                )
            ]
        }
    )
    with pytest.raises(QAError, match="do not match"):
        _language(mismatched)


def test_unknown_hearing_flag_fails() -> None:
    version = _version(
        spoken=[
            SpokenLine(
                shot_id="S01",
                voiceover="先看这台柱塞泵",
                subtitle="先看这台柱塞泵",
                transcript="先看这台柱塞泵",
                heard_check="",
            )
        ]
    )
    with pytest.raises(QAError, match="not checked"):
        _language(version)


def _version(**updates: object) -> DeliveryVersion:
    payload: dict[str, object] = {
        "version_id": "v",
        "aspect_ratio": "16:9",
        "language": "zh",
        "duration_s": 1,
        "width": 16,
        "height": 9,
        "path": "a.mp4",
        "picture_path": "b.mp4",
        "filters": "",
        "burn_filters": "",
        "geometry": [],
        "overlays": [],
        "spoken": [],
        "safe": {},
        "modes": {},
    }
    payload.update(updates)
    return DeliveryVersion.model_validate(payload)
