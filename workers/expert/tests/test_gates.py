"""Expert mode cannot mark an unreviewed shot passed, or skip the other gates."""

from __future__ import annotations

import uuid

import pytest

from workers.brand_kit.store import BrandRecord, save_record
from workers.expert.gates import (
    GateError,
    assert_ai_label,
    consent_gate,
    enforce_fonts,
    enforce_review,
    qa_passed_flag,
    scrub_brand,
    voice_allowlist,
)
from workers.expert.licenses import LicenseError, require_license
from workers.nodes.runtime import placeholder_qa
from workers.qa.scores import content_blocked
from workers.schemas.asset import Candidate, QAReport, QAScores
from workers.schemas.brand import (
    BrandColors,
    BrandFonts,
    BrandKit,
    BrandVoice,
    CallToAction,
    Industry,
    LogoAsset,
    Person,
)


def _report(**kwargs: object) -> QAReport:
    base = dict(
        scores=QAScores(
            product_fidelity=9,
            motion_quality=9,
            aesthetics=9,
            prompt_match=9,
            artifact_free=9,
        ),
        hard_fail=[],
        total=9.0,
        evaluator="vlm-judge-v1",
        notes="quality_pass=true",
        visual_reviewed=True,
    )
    base.update(kwargs)
    return QAReport.model_validate(base)


def _candidate(report: QAReport, *, selected: bool = True) -> Candidate:
    return Candidate(
        candidate_id="c1",
        shot_id="S01",
        node="N8",
        model="mock-image",
        params={"seed": 1},
        uri="mock://image/1",
        qa=report,
        selected=selected,
    )


def test_unreviewed_output_is_not_a_pass() -> None:
    report = placeholder_qa(selected=True)
    assert report.visual_reviewed is False
    assert qa_passed_flag(report) is False
    kept = enforce_review(_candidate(report), report.model_copy(update={"visual_reviewed": False}))
    assert kept.qa.visual_reviewed is False
    assert qa_passed_flag(kept.qa) is False


def test_a_real_review_can_pass_and_sensitive_cannot_stay_selected() -> None:
    clean = _report()
    assert qa_passed_flag(clean) is True
    blocked = _report(hard_fail=["sensitive"], total=2.0, notes="quality_pass=false")
    assert content_blocked(blocked) is True
    kept = enforce_review(_candidate(blocked, selected=True), blocked)
    assert kept.selected is False


def test_caller_consent_does_not_put_a_voice_on_the_allowlist(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path))
    enterprise_id = str(uuid.uuid4())
    inline = _kit(consent=True, voice_id="clone-inline").model_dump(mode="json")
    scrubbed = scrub_brand(inline, enterprise_id)
    assert scrubbed is not None
    assert scrubbed["people"] == []
    assert voice_allowlist(enterprise_id) == set()
    with pytest.raises(GateError, match="授权名单"):
        consent_gate(enterprise_id, "clone-inline")


def test_archive_voice_is_allowed_and_inline_consent_is_not(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_BRAND_DIR", str(tmp_path))
    enterprise_id = str(uuid.uuid4())
    archived = _kit(consent=True, voice_id="clone-archive")
    save_record(
        BrandRecord(enterprise_id=enterprise_id, brand_kit=archived.model_dump(mode="json"))
    )
    assert voice_allowlist(enterprise_id) == {"clone-archive"}
    consent_gate(enterprise_id, "clone-archive")
    inline = _kit(consent=True, voice_id="clone-inline")
    inline.voice.tts_voice = "clone-inline"
    scrubbed = scrub_brand(inline.model_dump(mode="json"), enterprise_id)
    assert scrubbed is not None
    assert [person["voice_id"] for person in scrubbed["people"]] == ["clone-archive"]
    assert scrubbed["voice"]["tts_voice"] != "clone-inline"


def test_ai_label_and_font_license_are_not_optional() -> None:
    with pytest.raises(GateError, match="AI生成"):
        assert_ai_label([{"kind": "badge", "text": "30 MPa"}])
    assert_ai_label([{"kind": "ai_label", "text": "AI生成"}])
    records = enforce_fonts()
    assert {item.name for item in records} == {
        "NotoSansSC-Regular.otf",
        "NotoSansSC-Bold.otf",
    }
    with pytest.raises(LicenseError, match="可商用授权"):
        require_license("PiratedFont.otf", "font")


def _kit(*, consent: bool, voice_id: str) -> BrandKit:
    return BrandKit(
        brand_id="brand-1",
        company_name="测试机械",
        industry=Industry.manufacturing,
        logo=LogoAsset(
            primary="brand://logo.png",
            mono_white="brand://logo-w.png",
            safe_area_ratio=0.1,
        ),
        colors=BrandColors(primary="#003366", secondary="#E8EEF4", accent="#F5A623"),
        fonts=BrandFonts(title="NotoSansSC-Bold", body="NotoSansSC-Regular"),
        products=[],
        people=[
            Person(
                person_id="p1",
                role="工程师",
                photos=["brand://person.png"],
                consent=consent,
                voice_id=voice_id,
            )
        ],
        voice=BrandVoice(tts_voice="zh_male_steady", speed=1.0),
        tone="稳重",
        cta=CallToAction(phone="", website="", wechat_qr=""),
        banned_words=["最"],
    )
