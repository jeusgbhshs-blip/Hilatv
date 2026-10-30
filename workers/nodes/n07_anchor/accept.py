"""T13 acceptance. Mock gateway only. No API key and no model download."""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

from workers.brand_kit.store import BrandRecord, save_record, write_asset
from workers.brand_kit.tests.images import noise_png
from workers.nodes.media_gateway import build_media_gateway
from workers.nodes.n07_anchor.identity import paint_face
from workers.nodes.n07_anchor.node import run
from workers.nodes.n07_anchor.qa import QAError, check
from workers.nodes.n07_anchor.samples import marked_product
from workers.qa.settings import deform_min_similarity, face_min_similarity
from workers.schemas.brand import BrandKit

ENTERPRISE = "44444444-4444-4444-8444-444444444444"
PHONE = "0532-00001111"


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="hilatv-t13-"))
    os.environ["HILATV_PROJECT_DIR"] = str(root / "projects")
    os.environ["HILATV_BRAND_DIR"] = str(root / "brands")
    os.environ["HILATV_LIVE"] = "0"
    os.environ["HILATV_BUDGET_CNY"] = "0"
    os.environ["HILATV_DAILY_BUDGET_CNY"] = "0"
    (root / "gateway").mkdir()
    gateway = build_media_gateway(root / "gateway")
    try:
        summary = _run(gateway)
    except Exception as exc:
        print(f"T13 accept: FAIL {exc}")
        return 1
    print(summary)
    return 0


def _run(gateway: object) -> str:
    product_id = _archive()
    result = run(
        {
            "project_id": "accept-t13",
            "payload": {
                "enterprise_id": ENTERPRISE,
                "brand_id": "brand-accept",
                "brief": _brief(),
                "script": _script(product_id),
                "concept": {
                    "ok": False,
                    "concept": {
                        "degraded": True,
                        "text_source": "template_fallback",
                        "directions": [{"source": "template_fallback"}],
                    },
                },
            },
        },
        gateway=gateway,
        max_attempts=1,
    )
    check(result)
    row = result.payload["candidates"][0]
    if result.payload["concept_passed"] is not False:
        raise AssertionError("degraded concept was treated as a pass")
    if row["qa"]["visual_reviewed"] is not False or row["selected"] is not False:
        raise AssertionError("mock composite was marked reviewed")
    edge_hits = _edge_rejection(gateway)
    threshold = deform_min_similarity()
    face = face_min_similarity()
    return (
        "T13 accept: "
        f"similarity={row['params']['similarity']:.3f} "
        f"threshold={threshold:.2f} "
        f"pixel_matches={row['params']['pixel_matches']} "
        f"face_cosine_min={result.payload['face_cosine_min']:.3f} "
        f"face_threshold={face:.2f} "
        f"garbled_scenes=0 "
        f"edge_reject={edge_hits} "
        f"concept_passed={result.payload['concept_passed']} "
        f"visual_reviewed={row['qa']['visual_reviewed']} "
        f"anchors={len(result.payload['anchors'])}"
    )


def _edge_rejection(gateway: object) -> int:
    import base64

    try:
        run(
            {
                "project_id": "accept-t13-edge",
                "payload": {
                    "products": [
                        {
                            "product_id": "noisy",
                            "name": "noisy",
                            "image_b64": base64.b64encode(noise_png()).decode("ascii"),
                        }
                    ],
                    "script": _script("noisy"),
                },
            },
            gateway=gateway,
            max_attempts=1,
        )
    except QAError as exc:
        if "请更换图片" not in str(exc) or exc.retryable:
            raise
        return 1
    raise AssertionError("bad matte did not ask for a replacement image")


def _archive() -> str:
    photo = write_asset(ENTERPRISE, "pump.png", marked_product())
    logo = write_asset(ENTERPRISE, "logo.png", marked_product())
    portrait = io.BytesIO()
    paint_face().save(portrait, format="PNG")
    face = write_asset(ENTERPRISE, "engineer.png", portrait.getvalue())
    product_id = "pump-accept"
    kit = {
        "brand_id": "brand-accept",
        "company_name": "测试机械",
        "industry": "manufacturing",
        "logo": {"primary": logo, "mono_white": logo, "safe_area_ratio": 0.2},
        "colors": {"primary": "#0A3D91", "secondary": "#FFFFFF", "accent": "#F5A623"},
        "fonts": {"title": "NotoSansSC-Bold", "body": "NotoSansSC-Regular"},
        "products": [
            {
                "product_id": product_id,
                "name": "测试泵 TP-1",
                "photos": [photo],
                "cutouts": [],
                "selling_points": ["压力 30MPa"],
                "forbidden_changes": ["铭牌文字"],
            }
        ],
        "people": [
            {
                "person_id": "engineer-1",
                "role": "工程师",
                "photos": [face],
                "consent": True,
                "voice_id": None,
            }
        ],
        "voice": {"tts_voice": "zh_male_steady", "speed": 1.0},
        "tone": "专业",
        "banned_words": [],
        "cta": {"phone": PHONE, "website": "", "wechat_qr": ""},
    }
    BrandKit.model_validate(kit)
    save_record(BrandRecord(enterprise_id=ENTERPRISE, brand_kit=kit))
    return product_id


def _brief() -> dict[str, object]:
    return {
        "brief_id": "brief-accept",
        "raw_input": "给测试泵做一条宣传片",
        "goal": "产品宣传",
        "platform": ["视频号"],
        "duration_s": 15,
        "aspect_ratios": ["16:9"],
        "languages": ["zh"],
        "video_type": "product_showcase",
        "audience": "采购",
        "must_include": [],
        "style": f"稳重 {PHONE}",
        "assumptions": [],
        "open_questions": [],
    }


def _script(product_id: str) -> dict[str, object]:
    return {
        "script_id": "script-accept",
        "brief_id": "brief-accept",
        "language": "zh",
        "sections": [],
        "shots": [
            {
                "shot_id": "S01",
                "order": 1,
                "duration_s": 3,
                "purpose": "展示产品",
                "visual": "产品放在车间里",
                "shot_size": "medium",
                "camera": "static",
                "subject_refs": [f"product:{product_id}"],
                "scene_ref": "workshop",
                "voiceover": "看这个产品",
                "on_screen_text": [{"text": "30 MPa", "style": "spec_badge", "in": 0.2, "out": 2}],
                "transition_out": "cut",
                "generation_mode": "product_composite",
                "status": "pending",
            }
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
