"""N7 anchors, product pixels, consent, and the shared regen budget."""

from __future__ import annotations

import io
import json

import pytest

from workers.brand_kit.store import BrandRecord, load_record, save_record, write_asset
from workers.brand_kit.tests.images import noise_png
from workers.nodes.n07_anchor.concept import classify_concept
from workers.nodes.n07_anchor.identity import min_view_cosine, paint_face, views_from_face
from workers.nodes.n07_anchor.node import run
from workers.nodes.n07_anchor.qa import QAError
from workers.nodes.n07_anchor.samples import marked_product
from workers.qa.samples import _plate
from workers.qa.settings import deform_min_similarity, face_min_similarity
from workers.schemas.asset import QAReport, QAScores
from workers.schemas.brand import BrandKit

ENTERPRISE = "33333333-3333-4333-8333-333333333333"
SECRET = "secret-unconsented-face"
PHONE = "0532-00001111"


def test_three_views_share_a_face_and_are_not_the_same_bitmap() -> None:
    views = views_from_face(paint_face())
    assert min_view_cosine(views) >= face_min_similarity()
    blobs = {image.tobytes() for image in views.values()}
    assert len(blobs) == 3


def test_degraded_concept_is_not_a_pass() -> None:
    status, passed, style = classify_concept(
        {
            "ok": False,
            "concept": {
                "degraded": True,
                "text_source": "template_fallback",
                "directions": [
                    {"source": "template_fallback", "style_keywords": ["DEGRADED-STYLE"]}
                ],
            },
        }
    )
    assert status == "degraded"
    assert passed is False
    assert style == ""
    status, passed, _style = classify_concept(
        {"text_source": "model", "degraded": False, "directions": [{"style_keywords": ["cold"]}]}
    )
    assert status == "passed" and passed is True


def test_product_composite_keeps_original_pixels(gateway) -> None:
    product_id = _archive()
    result = run(
        _request(product_id, concept=_degraded()),
        gateway=gateway,
        max_attempts=1,
    )
    assert result.ok is True
    assert result.payload["concept_passed"] is False
    assert result.payload["concept_status"] == "degraded"
    assert result.payload["style_source"] == "brief"
    blob = json.dumps(result.payload, ensure_ascii=False)
    assert SECRET not in blob
    assert PHONE not in "\n".join(result.payload["prompts"])
    assert "30 MPa" not in "\n".join(result.payload["prompts"])
    assert "DEGRADED-STYLE" not in blob
    row = result.payload["candidates"][0]
    assert row["selected"] is False
    assert row["qa"]["visual_reviewed"] is False
    assert result.payload["counts_as_reviewed"]["S01"] is False
    assert row["params"]["similarity"] >= deform_min_similarity()
    assert row["params"]["pixel_matches"] > 0
    assert row["params"]["threshold"] == deform_min_similarity()
    assert result.payload["face_cosine_min"] >= face_min_similarity()
    angles = [item for item in result.payload["anchors"] if item["kind"] == "product_angle"]
    assert {item["view"] for item in angles} == {"side", "back"}
    assert all(item["on_screen"] is False for item in angles)
    stored = load_record(ENTERPRISE)
    assert stored is not None
    kinds = {item.get("kind") for item in stored.anchors}
    assert {"product_angle", "scene", "style", "character", "product_composite"} <= kinds


def test_reviewed_only_when_review_shot_says_so(gateway, monkeypatch) -> None:
    product_id = _archive()

    def _report(*, seen: bool) -> QAReport:
        return QAReport(
            scores=QAScores(
                product_fidelity=9,
                motion_quality=9,
                aesthetics=9,
                prompt_match=9,
                artifact_free=9,
            ),
            hard_fail=[],
            total=9,
            evaluator="vlm-judge-v1",
            notes="ok",
            visual_reviewed=seen,
            judges_used=2 if seen else 0,
        )

    monkeypatch.setattr(
        "workers.nodes.n07_anchor.node.review_shot",
        lambda payload, **kwargs: _report(seen=False),
    )
    hidden = run(_request(product_id, project_id="hidden"), gateway=gateway, max_attempts=1)
    assert hidden.payload["candidates"][0]["selected"] is False
    monkeypatch.setattr(
        "workers.nodes.n07_anchor.node.review_shot",
        lambda payload, **kwargs: _report(seen=True),
    )
    shown = run(_request(product_id, project_id="shown"), gateway=gateway, max_attempts=1)
    assert shown.payload["candidates"][0]["selected"] is True
    assert shown.payload["counts_as_reviewed"]["S01"] is True


def test_bad_edge_asks_for_a_replacement(gateway) -> None:
    with pytest.raises(QAError, match="请更换图片") as caught:
        run(
            {
                "project_id": "bad-edge",
                "payload": {
                    "products": [
                        {
                            "product_id": "noisy",
                            "name": "noisy",
                            "image_b64": _b64(noise_png()),
                        }
                    ],
                    "script": _script("noisy"),
                },
            },
            gateway=gateway,
            max_attempts=1,
        )
    assert caught.value.retryable is False


def test_client_paths_and_loopback_and_foreign_brand_are_refused(gateway) -> None:
    with pytest.raises(QAError, match="http"):
        run(
            {
                "project_id": "path",
                "payload": {
                    "products": [{"name": "pump", "uri": "/etc/passwd"}],
                    "script": _script("pump"),
                },
            },
            gateway=gateway,
            max_attempts=1,
        )
    with pytest.raises(QAError, match="not allowed"):
        run(
            {
                "project_id": "loop",
                "payload": {
                    "products": [{"name": "pump", "uri": "http://127.0.0.1/pump.png"}],
                    "script": _script("pump"),
                },
            },
            gateway=gateway,
            max_attempts=1,
        )
    foreign = _inline_kit()
    foreign["logo"]["primary"] = "brand://99999999-9999-4999-8999-999999999999/logo.png"
    with pytest.raises(QAError, match="outside this enterprise"):
        run(
            {
                "project_id": "foreign",
                "payload": {
                    "enterprise_id": ENTERPRISE,
                    "brand_kit": foreign,
                    "script": _script("x"),
                },
            },
            gateway=gateway,
            max_attempts=1,
        )
    with pytest.raises(QAError, match="enterprise_id"):
        run(
            {"project_id": "noid", "payload": {"brand_id": "brand-1"}},
            gateway=gateway,
            max_attempts=1,
        )


def test_inline_consent_does_not_unlock_a_person(gateway) -> None:
    kit = _inline_kit()
    kit["people"] = [
        {
            "person_id": "inline-person",
            "role": "老板",
            "photos": [f"brand://{ENTERPRISE}/{SECRET}.png"],
            "consent": True,
            "voice_id": None,
        }
    ]
    result = run(
        {
            "project_id": "inline",
            "payload": {
                "enterprise_id": ENTERPRISE,
                "brand_kit": kit,
                "products": [
                    {
                        "product_id": "pump",
                        "name": "pump",
                        "image_b64": _b64(marked_product()),
                    }
                ],
                "script": _script("pump"),
                "brief": _brief(),
            },
        },
        gateway=gateway,
        max_attempts=1,
    )
    assert result.payload["face_cosine_min"] is None
    assert SECRET not in json.dumps(result.payload)


def test_garbled_scenes_share_the_project_budget(gateway, monkeypatch) -> None:
    monkeypatch.setenv("HILATV_QA_PROJECT_RETRIES", "1")
    product_id = _archive()
    wrapped = _Garbled(gateway)
    script = _script(product_id, "workshop")
    script["shots"].append(_shot(product_id, "yard", "S02", order=2))
    with pytest.raises(QAError, match="乱码"):
        run(
            {
                "project_id": "budget-proj",
                "payload": {
                    "enterprise_id": ENTERPRISE,
                    "script": script,
                    "brief": _brief(),
                },
            },
            gateway=wrapped,
            max_attempts=1,
        )
    from workers.qa.budget_store import open_project_budget

    budget = open_project_budget("budget-proj")
    assert budget.used == 1
    assert budget.allow() is False


def test_second_run_reuses_the_cutout(gateway) -> None:
    product_id = _archive()
    body = _request(product_id, project_id="reuse")
    run(body, gateway=gateway, max_attempts=1)
    first = [row for row in gateway.store.list_logs(project_id="reuse") if row["task"] == "matte"]
    run(body, gateway=gateway, max_attempts=1)
    second = [row for row in gateway.store.list_logs(project_id="reuse") if row["task"] == "matte"]
    assert len(first) == 1
    assert len(second) == 1


class _Garbled:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.seen: dict[str, int] = {}

    def generate_image(self, prompt: str, **kwargs: object) -> dict[str, object]:
        if kwargs.get("shot_type") == "scene":
            ref = str(kwargs.get("shot_id") or "scene")
            self.seen[ref] = self.seen.get(ref, 0) + 1
            if self.seen[ref] == 1:
                image = _plate("rect", garbled=1)
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                store = self.inner.registry["mock"].store
                uri = store.put(f"bad-{ref}.png", buffer.getvalue(), "image/png")
                return {"uri": uri, "mock": True}
        return self.inner.generate_image(prompt, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


def _archive() -> str:
    photo = write_asset(ENTERPRISE, "pump.png", marked_product())
    portrait_buf = io.BytesIO()
    paint_face().save(portrait_buf, format="PNG")
    portrait = write_asset(ENTERPRISE, "engineer.png", portrait_buf.getvalue())
    logo = write_asset(ENTERPRISE, "logo.png", marked_product())
    product_id = "pump-1"
    kit = {
        "brand_id": "brand-1",
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
                "photos": [portrait],
                "consent": True,
                "voice_id": None,
            },
            {
                "person_id": "boss-secret",
                "role": "老板",
                "photos": [f"brand://{ENTERPRISE}/{SECRET}.png"],
                "consent": False,
                "voice_id": "secret-voice",
            },
        ],
        "voice": {"tts_voice": "zh_male_steady", "speed": 1.0},
        "tone": "专业",
        "banned_words": [],
        "cta": {"phone": PHONE, "website": "https://example.test", "wechat_qr": ""},
    }
    BrandKit.model_validate(kit)
    save_record(
        BrandRecord(
            enterprise_id=ENTERPRISE,
            brand_kit=kit,
            anchors=[],
            usable_people=["engineer-1"],
        )
    )
    return product_id


def _request(product_id: str, *, project_id: str = "proj-t13", concept: dict | None = None) -> dict:
    return {
        "project_id": project_id,
        "payload": {
            "enterprise_id": ENTERPRISE,
            "brand_id": "brand-1",
            "brief": _brief(),
            "script": _script(product_id),
            "concept": concept,
        },
    }


def _brief() -> dict:
    return {
        "brief_id": "brief-1",
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


def _script(product_id: str, scene: str = "workshop") -> dict:
    return {
        "script_id": "script-1",
        "brief_id": "brief-1",
        "language": "zh",
        "sections": [],
        "shots": [_shot(product_id, scene, "S01", order=1)],
    }


def _shot(product_id: str, scene: str, shot_id: str, *, order: int) -> dict:
    return {
        "shot_id": shot_id,
        "order": order,
        "duration_s": 3,
        "purpose": "展示产品",
        "visual": "产品放在车间里",
        "shot_size": "medium",
        "camera": "static",
        "subject_refs": [f"product:{product_id}"],
        "scene_ref": scene,
        "voiceover": "看这个产品",
        "on_screen_text": [{"text": "30 MPa", "style": "spec_badge", "in": 0.2, "out": 2}],
        "transition_out": "cut",
        "generation_mode": "product_composite",
        "status": "pending",
    }


def _degraded() -> dict:
    return {
        "ok": False,
        "concept": {
            "degraded": True,
            "text_source": "template_fallback",
            "directions": [
                {
                    "direction_id": "d1",
                    "source": "template_fallback",
                    "style_keywords": ["DEGRADED-STYLE"],
                }
            ],
        },
    }


def _inline_kit() -> dict:
    return {
        "brand_id": "inline-brand",
        "company_name": "临时",
        "industry": "manufacturing",
        "logo": {
            "primary": "oss://logo.png",
            "mono_white": "oss://logo-w.png",
            "safe_area_ratio": 0.2,
        },
        "colors": {"primary": "#0A3D91", "secondary": "#FFFFFF", "accent": "#F5A623"},
        "fonts": {"title": "NotoSansSC-Bold", "body": "NotoSansSC-Regular"},
        "products": [],
        "people": [],
        "voice": {"tts_voice": "zh_male_steady", "speed": 1.0},
        "tone": "专业",
        "banned_words": [],
        "cta": {"phone": "", "website": "", "wechat_qr": ""},
    }


def _b64(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode("ascii")
