"""Acceptance: one Brand Kit feeds two projects, and three concept cards differ."""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from pathlib import Path

from workers.brand_kit.tests.images import logo_png, product_png
from workers.nodes.n01_brief.industries import INDUSTRY_ORDER, load_industries
from workers.nodes.n02_brand_kit.node import run as run_brand
from workers.nodes.n03_concept.compose import card_text, compose_directions, pick_structures
from workers.nodes.n03_concept.node import run as run_concept
from workers.nodes.n03_concept.similarity import cosine
from workers.schemas.brand import default_banned_words, find_banned_words
from workers.workflow.brand import resolve_brand_kit

ENTERPRISE = "22222222-2222-4222-8222-222222222222"
_BRIEF = {
    "brief_id": "accept-brief",
    "raw_input": "给测试泵做一条15秒宣传片，面向采购",
    "goal": "产品宣传",
    "platform": ["视频号"],
    "duration_s": 15,
    "aspect_ratios": ["9:16"],
    "languages": ["zh"],
    "video_type": "product_showcase",
    "audience": "采购",
    "must_include": ["压力 30MPa"],
    "style": "稳重",
    "assumptions": [],
    "open_questions": [],
}


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="hilatv-t15-"))
    os.environ["HILATV_BRAND_DIR"] = str(root)
    os.environ["HILATV_LIVE"] = "0"
    built = run_brand(
        {
            "project_id": "accept-t15",
            "payload": {
                "mode": "build",
                "enterprise_id": ENTERPRISE,
                "company_name": "青岛测试机械",
                "industry": "manufacturing",
                "logo_b64": base64.b64encode(logo_png()).decode("ascii"),
                "phone": "0532-00001111",
                "website": "https://example.test",
                "products": [
                    {
                        "name": "测试泵 TP-1",
                        "photo_b64": base64.b64encode(product_png()).decode("ascii"),
                        "selling_points": ["压力 30MPa"],
                        "forbidden_changes": ["铭牌文字"],
                    }
                ],
                "people": [{"role": "老板", "consent": False}],
            },
        },
        max_attempts=1,
    )
    kit = built.payload["brand_kit"]
    if any(person["role"] == "老板" or person["consent"] is not True for person in kit["people"]):
        print("unconsented person was released downstream", file=sys.stderr)
        return 1
    from workers.brand_kit import people_for_use
    from workers.schemas.brand import BrandKit

    if people_for_use(BrandKit.model_validate(kit)):
        print("t13 consumer saw a person from a kit with no consented portrait", file=sys.stderr)
        return 1
    loaded = []
    for project_id in ("film-a", "film-b"):
        item = resolve_brand_kit(
            inline=None,
            brand_id=None,
            enterprise_id=ENTERPRISE,
            project_id=project_id,
            attempt=1,
        )
        if item is None:
            print(f"{project_id} did not reuse the kit", file=sys.stderr)
            return 1
        loaded.append(item)
    for key in ("logo", "colors", "fonts", "cta"):
        if loaded[0][key] != loaded[1][key] or loaded[0][key] != kit[key]:
            print(f"{key} was not reused", file=sys.stderr)
            return 1
    points = loaded[0]["products"][0]["selling_points"]
    if points != loaded[1]["products"][0]["selling_points"] or "压力 30MPa" not in points:
        print("selling points were not reused", file=sys.stderr)
        return 1
    banned = default_banned_words()
    templates = load_industries()
    for industry in INDUSTRY_ORDER:
        structures = pick_structures(templates[industry])
        cards = compose_directions(templates[industry], structures, banned=banned)
        texts = [card_text(card) for card in cards]
        for index, left in enumerate(texts):
            if find_banned_words(left, banned):
                print(f"{industry} uses a banned word", file=sys.stderr)
                return 1
            for right in texts[index + 1 :]:
                score = cosine(left, right)
                if score >= 0.85:
                    print(f"{industry} cards are too similar: {score:.3f}", file=sys.stderr)
                    return 1
    concept = run_concept(
        {"project_id": "accept-t15-concept", "payload": {"brief": _BRIEF, "brand_kit": kit}},
        max_attempts=1,
    ).payload["concept"]
    directions = concept["directions"]
    if concept["selection"] != "你帮我选" or len(directions) != 3:
        print("N3 did not offer three cards and 你帮我选", file=sys.stderr)
        return 1
    if concept.get("degraded") is not True or concept.get("text_source") != "template_fallback":
        print("mock draft was treated as a real pass", file=sys.stderr)
        return 1
    if any(item.get("source") != "template_fallback" for item in directions):
        print("template fallback was not marked", file=sys.stderr)
        return 1
    if any(item.get("cover_status") != "not_ready" or item.get("cover_uri") for item in directions):
        print("mock cover was treated as ready", file=sys.stderr)
        return 1
    print("accept-t15 ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
