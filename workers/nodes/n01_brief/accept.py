"""Run the 20 N1 fixtures and print a Brief for each.

``HILATV_LIVE=1`` with a key and a positive budget still has to return a legal
Brief. Field-level expectations are checked on the mock path, because a live
model may fill gaps the rules would otherwise default.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from workers.nodes.n01_brief.node import run
from workers.nodes.n01_brief.platforms import aspects_match
from workers.nodes.n01_brief.prompts import NO_DRAWN_TEXT
from workers.nodes.n01_brief.ssrf import fetch_hooks
from workers.schemas.brief import Brief

FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"
# Reserved `.test` name. The suite never dials this address; the mock transport
# reads the fixture files after the SSRF guard has accepted the pinned IP.
FIXTURE_FETCH_HOST = "assets.hilatv.test"
FIXTURE_FETCH_IP = "93.184.216.34"


def main() -> int:
    from gateway import get_gateway, reset_gateway

    reset_gateway()
    strict = not live_enabled()
    failures = run_suite(get_gateway(), strict=strict)
    if failures:
        print(f"T05 accept: FAIL {len(failures)}")
        return 1
    mode = "live" if not strict else "mock"
    print(f"T05 accept: 20/20 briefs valid ({mode})")
    return 0


def live_enabled() -> bool:
    if os.getenv("HILATV_LIVE", "").strip() != "1":
        return False
    keyed = any(
        os.getenv(name, "").strip()
        for name in ("DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "ARK_API_KEY")
    )
    if not keyed:
        return False
    total = Decimal(os.getenv("HILATV_BUDGET_CNY", "0") or "0")
    daily = Decimal(os.getenv("HILATV_DAILY_BUDGET_CNY", "0") or "0")
    return total > 0 and daily > 0


def run_suite(gateway: Any, *, strict: bool = True) -> list[str]:
    failures: list[str] = []
    with fixture_fetch():
        for path in sorted(FIXTURES.glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            case_id = str(case.get("id") or path.stem)
            try:
                result = run(case["request"], gateway=gateway)
                brief = Brief.model_validate(result.payload["brief"])
                errors = evaluate(brief, case.get("expect") or {}, result.payload, strict=strict)
            except Exception as exc:
                errors = [str(exc)]
                brief = None
            if errors:
                detail = "" if brief is None else " " + _snapshot(brief)
                failures.append(f"{case_id}: {'; '.join(errors)}{detail}")
                print(f"[fail] {case_id}: {'; '.join(errors)}{detail}")
            else:
                assert brief is not None
                print(
                    f"[ok] {case_id} duration={brief.duration_s} "
                    f"questions={len(brief.open_questions)} "
                    f"video_type={brief.video_type} "
                    f"platforms={','.join(brief.platform)}"
                )
    return failures


def evaluate(
    brief: Brief,
    expect: dict[str, Any],
    payload: dict[str, Any],
    *,
    strict: bool,
) -> list[str]:
    errors: list[str] = []
    if not 5 <= brief.duration_s <= 180:
        errors.append(f"duration {brief.duration_s}")
    if not aspects_match(brief.platform, brief.aspect_ratios):
        errors.append("platform/aspect mismatch")
    if len(brief.open_questions) > 2:
        errors.append("more than 2 questions")
    for question in brief.open_questions:
        if not question.options or question.recommended not in question.options:
            errors.append("question missing recommended option")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or NO_DRAWN_TEXT not in prompt:
        errors.append("prompt missing no-drawn-text constraint")
    if not strict:
        return errors
    raw_input = expect.get("raw_input")
    if raw_input is not None and brief.raw_input != raw_input:
        errors.append("raw_input changed")
    _eq(errors, "duration_s", brief.duration_s, expect)
    _eq(errors, "languages", brief.languages, expect)
    _eq(errors, "platforms", brief.platform, expect, field="platforms")
    _eq(errors, "aspect_ratios", brief.aspect_ratios, expect)
    _eq(errors, "video_type", brief.video_type, expect)
    _eq(errors, "goal", brief.goal, expect)
    _eq(errors, "style", brief.style, expect)
    _eq(errors, "audience", brief.audience, expect)
    if "max_questions" in expect and len(brief.open_questions) > expect["max_questions"]:
        errors.append(f"questions {len(brief.open_questions)} > {expect['max_questions']}")
    if "min_questions" in expect and len(brief.open_questions) < expect["min_questions"]:
        errors.append(f"questions {len(brief.open_questions)} < {expect['min_questions']}")
    for needle in expect.get("assumption_contains") or []:
        if not any(needle in item for item in brief.assumptions):
            errors.append(f"assumption missing {needle}")
    for needle in expect.get("must_include_contains") or []:
        if not any(needle in item for item in brief.must_include):
            errors.append(f"must_include missing {needle}")
    for needle in expect.get("question_contains") or []:
        if not any(needle in item.question for item in brief.open_questions):
            errors.append(f"question missing {needle}")
    if "image_classes" in expect:
        found = _image_classes(payload.get("attachments") or [])
        if found != expect["image_classes"]:
            errors.append(f"image classes {found}")
    if expect.get("images_downloaded"):
        sizes = [
            image.get("bytes", 0)
            for item in payload.get("attachments") or []
            for image in item.get("images") or []
        ]
        if not sizes or any(not isinstance(size, int) or size <= 0 for size in sizes):
            errors.append(f"images not downloaded {sizes}")
    return errors


@contextmanager
def fixture_fetch() -> Iterator[None]:
    """Serve N1 fixture pages without binding a loopback socket."""

    assets = FIXTURES / "assets"
    root = assets.resolve()

    def resolver(host: str, port: int) -> list[str]:
        if host == FIXTURE_FETCH_HOST:
            return [FIXTURE_FETCH_IP]
        raise OSError(f"fixture host is not mapped: {host}")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != FIXTURE_FETCH_IP:
            return httpx.Response(421)
        relative = request.url.path.lstrip("/")
        candidate = (assets / relative).resolve()
        if candidate != root and root not in candidate.parents:
            return httpx.Response(404)
        if not candidate.is_file():
            return httpx.Response(404)
        media = {
            ".html": "text/html; charset=utf-8",
            ".png": "image/png",
            ".pdf": "application/pdf",
        }.get(candidate.suffix.lower(), "application/octet-stream")
        return httpx.Response(200, content=candidate.read_bytes(), headers={"content-type": media})

    with fetch_hooks(resolver=resolver, transport=httpx.MockTransport(handler)):
        yield


def _image_classes(attachments: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for item in attachments:
        if item.get("kind") == "image" and item.get("image_class"):
            found.append(str(item["image_class"]))
        if item.get("kind") == "url":
            for image in item.get("images") or []:
                if image.get("image_class"):
                    found.append(str(image["image_class"]))
    return found


def _eq(
    errors: list[str],
    name: str,
    actual: object,
    expect: dict[str, Any],
    *,
    field: str | None = None,
) -> None:
    key = field or name
    if key in expect and actual != expect[key]:
        errors.append(f"{name}={actual!r}")


def _snapshot(brief: Brief) -> str:
    payload = {
        "goal": brief.goal,
        "platform": brief.platform,
        "duration_s": brief.duration_s,
        "aspect_ratios": brief.aspect_ratios,
        "languages": brief.languages,
        "video_type": brief.video_type,
        "audience": brief.audience,
        "must_include": brief.must_include,
        "style": brief.style,
        "assumptions": brief.assumptions,
        "questions": [item.question for item in brief.open_questions],
    }
    return json.dumps(payload, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
