"""Saved generation settings are strict and safe to use as submission identity."""

import pytest
from pydantic import ValidationError

from workers.schemas.generation import GenerationSettings, generation_settings

RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "4:5", "21:9")


def test_missing_settings_are_explicitly_auto():
    assert generation_settings().model_dump() == {"aspect_ratio": None, "duration_s": None}
    assert GenerationSettings.model_validate({}) == generation_settings()


@pytest.mark.parametrize("ratio", RATIOS)
@pytest.mark.parametrize("duration", [5, 15, 180])
def test_supported_settings_roundtrip(ratio, duration):
    raw = {"aspect_ratio": ratio, "duration_s": duration}
    assert GenerationSettings.model_validate(raw).model_dump() == raw


@pytest.mark.parametrize("duration", [True, False, 15.0, "15", 4, 181, -1, [], {}])
def test_duration_is_an_integer_in_supported_bounds(duration):
    with pytest.raises(ValidationError):
        GenerationSettings(duration_s=duration)


@pytest.mark.parametrize("raw", [{"aspect_ratio": "2:1"}, {"fps": 30}, {"duration": 15}])
def test_unknown_aspects_and_extra_fields_are_rejected(raw):
    with pytest.raises(ValidationError):
        GenerationSettings.model_validate(raw)
