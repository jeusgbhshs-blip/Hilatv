"""A voice id is allowed only from the server list or the brand archive."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gateway.constants import BUILTIN_TTS_VOICES, DEFAULT_TTS_VOICE
from workers.brand_kit.people import ConsentError
from workers.brand_kit.store import BrandRecord, save_record
from workers.compliance.consent_gate import assert_voice_allowed
from workers.schemas.brand import BrandKit

_ROOT = Path(__file__).resolve().parents[3]
_EID = "11111111-1111-4111-8111-111111111111"
_OTHER = "22222222-2222-4222-8222-222222222222"
_CLONE = "clone-boss-voice"


@pytest.fixture
def brand_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path))
    return tmp_path


def _kit(*, people: list[dict] | None = None, voice: str = "zh_male_steady") -> BrandKit:
    raw = json.loads(
        (_ROOT / "workers/schemas/tests/fixtures/brand_kit.json").read_text(encoding="utf-8")
    )
    if people is not None:
        raw["people"] = people
    raw["voice"]["tts_voice"] = voice
    return BrandKit.model_validate(raw)


def _person(voice_id: str | None, *, consent: bool = True) -> dict:
    return {
        "person_id": "boss",
        "role": "老板",
        "photos": [],
        "consent": consent,
        "voice_id": voice_id,
    }


def test_clone_omitted_from_the_request_is_rejected(brand_dir: Path) -> None:
    """The old gate treated a missing person as stock TTS. That must fail."""

    request = _kit(people=[], voice=_CLONE)
    with pytest.raises(ConsentError, match="声音"):
        assert_voice_allowed(_CLONE, _EID, request)
    claimed = _kit(people=[_person(_CLONE, consent=True)], voice=_CLONE)
    with pytest.raises(ConsentError, match="声音"):
        assert_voice_allowed(_CLONE, _EID, claimed)


def test_unknown_voice_is_rejected(brand_dir: Path) -> None:
    with pytest.raises(ConsentError, match="声音"):
        assert_voice_allowed("not-a-gateway-voice", _EID, None)
    assert "not-a-gateway-voice" not in BUILTIN_TTS_VOICES


def test_builtin_voice_passes(brand_dir: Path) -> None:
    request = _kit(people=[], voice="zh_male_steady")
    assert_voice_allowed("zh_male_steady", _EID, request)
    assert_voice_allowed("zh_female_steady", _EID, request)
    assert_voice_allowed(DEFAULT_TTS_VOICE, None, request)
    assert_voice_allowed(None, _EID, request)


def test_archived_authorized_clone_passes(brand_dir: Path) -> None:
    stored = _kit(people=[_person(_CLONE)], voice="zh_male_steady")
    save_record(BrandRecord(enterprise_id=_EID, brand_kit=stored.model_dump(mode="json")))
    request = _kit(people=[], voice=_CLONE)
    assert_voice_allowed(_CLONE, _EID, request)
    with pytest.raises(ConsentError, match="声音"):
        assert_voice_allowed(_CLONE, _OTHER, request)


def test_archive_without_consent_does_not_release_the_clone(brand_dir: Path) -> None:
    stored = _kit(people=[_person(_CLONE, consent=False)], voice="zh_male_steady")
    save_record(BrandRecord(enterprise_id=_EID, brand_kit=stored.model_dump(mode="json")))
    request = _kit(people=[], voice=_CLONE)
    with pytest.raises(ConsentError, match="声音"):
        assert_voice_allowed(_CLONE, _EID, request)
