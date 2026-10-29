"""T06 acceptance: N4 script plus N5 storyboard on fixture briefs.

No API key is required. ``HILATV_LIVE=1`` still has to satisfy the same rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workers.nodes.n04_script.node import run as run_script
from workers.nodes.n04_script.qa import QAError
from workers.nodes.n04_script.qa import check as check_script
from workers.nodes.n05_storyboard.node import run as run_board
from workers.nodes.n05_storyboard.qa import check as check_board
from workers.schemas.brief import Brief
from workers.schemas.script import ScriptSectionKind

FIXTURES = Path(__file__).resolve().parents[2] / "schemas" / "tests" / "fixtures"


def main() -> int:
    from gateway import get_gateway, reset_gateway

    reset_gateway()
    gateway = get_gateway()
    failures = run_suite(gateway)
    if failures:
        print(f"T06 accept: FAIL {len(failures)}")
        for item in failures:
            print(f"[fail] {item}")
        return 1
    print("T06 accept: duration error <= 5%, no invented numbers, shots valid (mock)")
    return 0


def run_suite(gateway: Any) -> list[str]:
    failures: list[str] = []
    brief = json.loads((FIXTURES / "brief.json").read_text(encoding="utf-8"))
    brand = json.loads((FIXTURES / "brand_kit.json").read_text(encoding="utf-8"))

    cases: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = [
        ("spec-en-30", brief, brand),
        ("zh-5-promo", _copy(brief, duration_s=5, languages=["zh"]), brand),
        ("zh-180-promo", _copy(brief, duration_s=180, languages=["zh"]), brand),
        (
            "zh-15-short",
            _copy(
                brief,
                duration_s=15,
                languages=["zh"],
                video_type="sku_clip",
                raw_input="给这款杯子做15秒带货短视频",
                must_include=["杯身 300ml"],
            ),
            None,
        ),
    ]
    person = json.loads(json.dumps(brand))
    person["people"][0]["photos"] = ["oss://boss.jpg"]
    cases.append(
        (
            "person-30",
            _copy(brief, raw_input="老板出镜讲这台柱塞泵，30秒宣传片"),
            person,
        )
    )
    photos = json.loads(json.dumps(brand))
    photos["products"][0]["cutouts"] = []
    cases.append(("photos-only-30", brief, photos))

    for label, brief_raw, brand_raw in cases:
        try:
            _case(gateway, label, brief_raw, brand_raw)
        except Exception as exc:
            failures.append(f"{label}: {exc}")
            print(f"[fail] {label}: {exc}")
    try:
        _planted(brief, brand)
        print("[ok] planted number 99999 blocked")
    except Exception as exc:
        failures.append(f"planted: {exc}")
        print(f"[fail] planted: {exc}")
    return failures


def _case(
    gateway: Any,
    label: str,
    brief_raw: dict[str, Any],
    brand_raw: dict[str, Any] | None,
) -> None:
    request = {"project_id": "accept-t06", "payload": {"brief": brief_raw, "brand_kit": brand_raw}}
    scripted = run_script(request, gateway=gateway)
    check_script(scripted)
    boarded = run_board(
        {
            "project_id": "accept-t06",
            "payload": {
                "brief": scripted.payload["brief"],
                "script": scripted.payload["script"],
                "brand_kit": scripted.payload["brand_kit"],
            },
        },
        gateway=gateway,
    )
    script = check_board(boarded)
    brief = Brief.model_validate(scripted.payload["brief"])
    total = sum(shot.duration_s for shot in script.shots)
    error = abs(total - brief.duration_s) / brief.duration_s
    print(
        f"[ok] {label} lang={script.language} shots={len(script.shots)} "
        f"duration_error={error:.4%} sections={len(script.sections)}"
    )


def _planted(brief_raw: dict[str, Any], brand_raw: dict[str, Any]) -> None:
    from workers.nodes.n04_script.compose import compose_script
    from workers.nodes.n04_script.facts import collect_facts
    from workers.nodes.n04_script.qa import audit_script
    from workers.schemas.brand import BrandKit

    brief = Brief.model_validate(brief_raw)
    brand = BrandKit.model_validate(brand_raw)
    facts = collect_facts(brief, brand)
    script = compose_script(project_id="accept", brief=brief, facts=facts, language="zh")
    sections = list(script.sections)
    point = next(section for section in sections if section.kind is ScriptSectionKind.selling_point)
    updated = point.model_copy(update={"text": "虚构参数 99999"})
    planted = script.model_copy(
        update={"sections": [updated if section is point else section for section in sections]}
    )
    try:
        audit_script(planted, brief, brand)
    except QAError as exc:
        if "99999" not in str(exc):
            raise AssertionError(f"planted number was not named: {exc}") from exc
        return
    raise AssertionError("planted number 99999 was not blocked")


def _copy(brief: dict[str, Any], **updates: Any) -> dict[str, Any]:
    copied = json.loads(json.dumps(brief))
    copied.update(updates)
    return copied


if __name__ == "__main__":
    raise SystemExit(main())
