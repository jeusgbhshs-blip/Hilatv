"""One entry, two later projects. Logo, color, type, CTA, and points stay put."""

from __future__ import annotations

import base64
import uuid

import pytest

from workers.brand_kit.people import ConsentError, require_consent
from workers.brand_kit.points import PreferenceEdit, Replacement
from workers.brand_kit.tests.images import logo_png, noise_png, product_png
from workers.nodes.n02_brand_kit.node import run
from workers.nodes.n02_brand_kit.qa import QAError
from workers.workflow.brand import resolve_brand_kit

ENTERPRISE = "11111111-1111-4111-8111-111111111111"


def _build(gateway, *, people=None, logo=None, points=None):
    return run(
        {
            "project_id": "build",
            "payload": {
                "mode": "build",
                "enterprise_id": ENTERPRISE,
                "company_name": "青岛测试机械",
                "industry": "manufacturing",
                "logo_b64": base64.b64encode(logo or logo_png()).decode("ascii"),
                "phone": "0532-00001111",
                "website": "https://example.test",
                "products": [
                    {
                        "name": "测试泵 TP-1",
                        "photo_b64": base64.b64encode(product_png()).decode("ascii"),
                        "selling_points": points or ["压力 30MPa", "寿命 2 万小时"],
                        "source_text": "压力 30MPa。寿命 2 万小时。",
                        "forbidden_changes": ["铭牌文字"],
                    }
                ],
                "people": people or [],
            },
        },
        gateway=gateway,
        max_attempts=1,
    )


def test_two_projects_reuse_the_same_kit(gateway, brand_dir) -> None:
    assert brand_dir is not None
    built = _build(gateway)
    kit = built.payload["brand_kit"]
    assert kit["cta"]["phone"] == "0532-00001111"
    anchors = built.payload["anchors"]
    assert len(anchors) == 2
    assert all(item["on_screen"] is False for item in anchors)
    screen = set(kit["products"][0]["photos"] + kit["products"][0]["cutouts"])
    assert {item["uri"] for item in anchors}.isdisjoint(screen)
    first = resolve_brand_kit(
        inline=None,
        brand_id=None,
        enterprise_id=ENTERPRISE,
        project_id="project-a",
        attempt=1,
    )
    second = resolve_brand_kit(
        inline=None,
        brand_id=None,
        enterprise_id=ENTERPRISE,
        project_id="project-b",
        attempt=1,
    )
    assert first is not None and second is not None
    for key in ("logo", "colors", "fonts", "cta"):
        assert first[key] == second[key] == kit[key]
    assert first["products"][0]["selling_points"] == second["products"][0]["selling_points"]
    assert "压力 30MPa" in first["products"][0]["selling_points"]
    logs = gateway.store.list_logs(project_id="build")
    prompts = [row["params"]["prompt"] for row in logs if row["task"] == "image"]
    assert prompts
    assert all("不直接上屏" in prompt for prompt in prompts)
    assert all("0532-00001111" not in prompt for prompt in prompts)


def test_bad_edge_tells_the_user_to_replace_the_picture(gateway, brand_dir) -> None:
    try:
        _build(gateway, logo=noise_png())
    except QAError as exc:
        assert exc.retryable is False
        assert "请更换图片" in str(exc)
    else:
        raise AssertionError("speckled logo should fail the edge check")


def test_voice_without_consent_is_rejected(gateway, brand_dir) -> None:
    try:
        _build(gateway, people=[{"role": "老板", "consent": False, "voice_id": "clone-1"}])
    except QAError as exc:
        assert "声音" in str(exc)
    else:
        raise AssertionError("voice clone without consent should fail")


def test_unconsented_person_is_stored_but_not_usable(gateway, brand_dir) -> None:
    result = _build(
        gateway,
        people=[
            {"role": "老板", "consent": False, "voice_id": None},
            {"role": "工程师", "consent": True, "voice_id": None},
        ],
    )
    people = result.payload["brand_kit"]["people"]
    assert [person["consent"] for person in people] == [False, True]
    usable = set(result.payload["usable_people"])
    assert people[0]["person_id"] not in usable
    assert people[1]["person_id"] in usable
    with pytest.raises(ConsentError):
        from workers.schemas.brand import Person

        require_consent(Person.model_validate(people[0]))


def test_preference_writeback_is_what_the_next_project_reads(gateway, brand_dir) -> None:
    _build(gateway)
    run(
        {
            "project_id": "edit",
            "payload": {
                "mode": "preference",
                "enterprise_id": ENTERPRISE,
                "preference": PreferenceEdit(
                    product_name="测试泵 TP-1",
                    replacements=[Replacement(old="压力 30MPa", new="压力 28MPa")],
                    drop_lines=["寿命 2 万小时"],
                ).model_dump(),
            },
        },
        gateway=gateway,
        max_attempts=1,
    )
    again = resolve_brand_kit(
        inline=None,
        brand_id=None,
        enterprise_id=str(uuid.UUID(ENTERPRISE)),
        project_id="project-c",
        attempt=1,
    )
    points = again["products"][0]["selling_points"]
    assert points == ["压力 28MPa"]
    assert "寿命 2 万小时" in again["banned_words"]
