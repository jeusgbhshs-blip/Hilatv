"""T16 acceptance. The edit set is hand-written; expectations are not parser output.

Success: the change matches that intent, and shots outside the target keep
every field. Logo edits must not log a video call. Unaffected shot files keep
their hash. Any saved version can be restored. Mock only.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from workers.nodes.n18_revision.corpus import evaluate
from workers.workflow.revise import revise_project
from workers.workflow.store import init_project, project_path, update_snapshot
from workers.workflow.versions import hashes, restore_version


def main() -> None:
    os.environ["HILATV_LIVE"] = "0"
    os.environ["HILATV_BUDGET_CNY"] = "0"
    os.environ["HILATV_DAILY_BUDGET_CNY"] = "0"
    os.environ.setdefault("HILATV_RENDER_WIDTH", "160")
    os.environ.setdefault("HILATV_RENDER_HEIGHT", "90")
    os.environ.setdefault("HILATV_SHOT_WORKERS", "2")
    gateway = _plain_mock()
    report = evaluate(gateway=gateway)
    from workers.nodes.n18_revision.unseen import evaluate_unseen

    unseen = evaluate_unseen(gateway=gateway)
    print(f"self_built_cases={report['total']}")
    print(f"self_built_success={report['passed']}")
    print(f"self_built_success_rate={report['rate']:.3f}")
    print("self_built_set=hand-written; scored against the same mock parser")
    print(f"unseen_cases={unseen['total']}")
    print(f"unseen_success={unseen['passed']}")
    print(f"unseen_success_rate={unseen['rate']:.3f}")
    print("unseen_bar=0.85")
    print(f"unseen_bar_met={str(unseen['rate'] >= 0.85).lower()}")
    print(
        "unseen_note=mock LLM fills the schema with placeholders and does not read the sentence; "
        "supported edits become needs_clarification. Unsupported edits are refused. "
        "The 85% bar is for a model that returns a real change set; it is not met under mock."
    )
    if unseen["unsafe_blanket"] or report["blanket_regens"]:
        raise SystemExit("an unclear edit regenerated every shot")
    stats = _media()
    print(f"logo_video_calls={stats['logo_video_calls']}")
    print(f"logo_end_card_note={stats['end_card']}")
    print(f"failed_video={stats['failed_video']}")
    print(f"unaffected_hashes={stats['unaffected']}")
    print(f"rollback={stats['rollback']}")
    print(f"quality_pass_after_regen={stats['quality_pass']}")
    print(f"degraded_concept_pass={stats['degraded_pass']}")
    if stats["logo_video_calls"] != 0:
        raise SystemExit("logo edit logged a video call")
    if stats["end_card"] != "shown":
        raise SystemExit("logo removal did not say the end card stays")
    if stats["failed_video"] != "kept":
        raise SystemExit("a missing video was presented as a new picture")
    if stats["unaffected"] != "stable":
        raise SystemExit("unaffected shot hashes changed")
    if stats["rollback"] != "ok":
        raise SystemExit("rollback failed")
    if stats["quality_pass"] is not False or stats["degraded_pass"] is not False:
        raise SystemExit("an unreviewed or degraded result was marked passing")
    print("accept-t16 ok")


def _plain_mock() -> Any:
    from workers.workflow.revise import revision_gateway

    folder = Path(os.environ.get("HILATV_PROJECT_DIR") or "/tmp") / "t16-parse-gateway"
    return revision_gateway(folder)


class _Scripted:
    """Media-path double. The success rates do not use this object."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def generate_text(self, prompt: str, **kwargs: Any) -> dict[str, Any]:
        if "去掉 Logo" in prompt:
            return {
                "targets": ["S01", "S02", "S03"],
                "change": {"logo": "remove"},
                "keep": ["narration", "composition"],
            }
        if "第二个镜头太暗" in prompt:
            return {
                "targets": ["S02"],
                "change": {"lighting": "brighter"},
                "keep": ["composition", "narration"],
            }
        if "把价格去掉" in prompt:
            return {
                "targets": ["S01", "S02", "S03"],
                "change": {"price": "remove"},
                "keep": ["narration", "logo"],
            }
        return self._inner.generate_text(prompt, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _media() -> dict[str, Any]:
    root = Path(
        os.environ.get("HILATV_PROJECT_DIR") or Path(os.getenv("TMPDIR", "/tmp")) / "hilatv-t16"
    )
    root.mkdir(parents=True, exist_ok=True)
    os.environ["HILATV_PROJECT_DIR"] = str(root)
    project_id = "t16accept"
    _seed(project_id)
    directory = project_path(project_id)
    gateway = _Scripted(_plain_mock_at(directory))
    before = hashes(directory)
    master = directory / "playback" / "master.mp4"
    original_master = master.read_bytes()
    video_before = _video_calls(gateway, project_id)
    logo = revise_project(project_id, "去掉 Logo", gateway=gateway)
    video_after = _video_calls(gateway, project_id)
    after_logo = hashes(directory)
    logo_master = master.read_bytes()
    if before != after_logo or video_after != video_before:
        return _fail("video" if video_after != video_before else "changed")
    if "片尾" not in str(logo.get("notice") or ""):
        return _fail("notice")
    versions = logo["version_id"]
    first = _current_ids(project_id)[0]
    lighting = revise_project(project_id, "第二个镜头太暗", gateway=gateway)
    after_light = hashes(directory)
    light_master = master.read_bytes()
    video_rows = [
        row for row in gateway.store.list_logs(project_id=project_id) if row.get("task") == "video"
    ]
    kept = lighting.get("status") == "incomplete" and "S02" in (lighting.get("kept_previous") or [])
    told = "保留" in str(lighting.get("notice") or "")
    if after_light != before or not kept or not told:
        return _fail("changed")
    if not video_rows or any(row.get("shot_id") != "S02" for row in video_rows):
        return _fail("video")
    if lighting["quality_pass"] is not False or logo["quality_pass"] is not False:
        return _fail("pass")
    notice = str(lighting.get("notice") or "")
    if lighting.get("status") == "completed" and "改稿已生成新版本" in notice:
        return _fail("pass")
    _degraded(project_id)
    degraded = revise_project(project_id, "把价格去掉", gateway=gateway)
    restored_first = restore_version(project_id, first)
    if hashes(directory) != before or master.read_bytes() != original_master:
        return _fail("rollback")
    restore_version(project_id, versions)
    if hashes(directory) != after_logo or master.read_bytes() != logo_master:
        return _fail("rollback")
    restore_version(project_id, lighting["version_id"])
    if hashes(directory) != after_light or master.read_bytes() != light_master:
        return _fail("rollback")
    if restored_first["versions"] and any(
        item["version_id"] == first and item["quality_pass"] is True
        for item in restored_first["versions"]
    ):
        return _fail("pass")
    return {
        "logo_video_calls": video_after - video_before,
        "end_card": "shown",
        "failed_video": "kept",
        "unaffected": "stable",
        "rollback": "ok",
        "quality_pass": lighting["quality_pass"],
        "degraded_pass": degraded["quality_pass"],
    }


def _plain_mock_at(directory: Path) -> Any:
    from workers.workflow.revise import revision_gateway

    return revision_gateway(directory)


def _fail(kind: str) -> dict[str, Any]:
    return {
        "logo_video_calls": 0 if kind != "video" else 1,
        "end_card": "missing" if kind == "notice" else "shown",
        "failed_video": "replaced" if kind == "changed" else "kept",
        "unaffected": "changed" if kind == "changed" else "stable",
        "rollback": "failed" if kind == "rollback" else "ok",
        "quality_pass": True if kind == "pass" else False,
        "degraded_pass": True if kind == "pass" else False,
    }


def _video_calls(gateway: Any, project_id: str) -> int:
    return sum(
        1 for row in gateway.store.list_logs(project_id=project_id) if row.get("task") == "video"
    )


def _current_ids(project_id: str) -> list[str]:
    from workers.workflow.versions import list_versions

    body = list_versions(project_id)
    return [item["version_id"] for item in body["versions"]]


def _seed(project_id: str) -> None:
    init_project(project_id, sentence="给我们的泵做一条短片", status="completed")
    script = _script()
    brief = _brief()
    brand = _brand()
    directory = project_path(project_id)
    nodes = directory / "nodes"
    nodes.mkdir(parents=True, exist_ok=True)
    _write(nodes / "n01_brief.json", {"brief": brief})
    _write(nodes / "n02_brand_kit.json", {"brand_kit": brand})
    _write(nodes / "n05_storyboard.json", {"script": script})
    media = directory / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / "S01.bin").write_bytes(_plate(1))
    (media / "S02.bin").write_bytes(_plate(2))
    (media / "S03.bin").write_bytes(_plate(3))
    master = directory / "playback" / "master.mp4"
    master.parent.mkdir(parents=True, exist_ok=True)
    master.write_bytes(b"original-master")
    update_snapshot(
        project_id,
        status="completed",
        sentence="给我们的泵做一条短片",
        deliverable=str(master),
        shots=[
            {"shot_id": shot["shot_id"], "order": shot["order"], "purpose": shot["purpose"]}
            for shot in script["shots"]
        ],
    )


def _degraded(project_id: str) -> None:
    directory = project_path(project_id)
    _write(
        directory / "nodes" / "n03_concept.json",
        {
            "concept": {
                "degraded": True,
                "ok": False,
                "text_source": "template_fallback",
                "selection": "你帮我选",
                "directions": [
                    {"direction_id": "a", "source": "template_fallback"},
                    {"direction_id": "b", "source": "template_fallback"},
                    {"direction_id": "c", "source": "template_fallback"},
                ],
            }
        },
    )


def _script() -> dict[str, Any]:
    def shot(shot_id: str, order: int, spoken: str, card: str | None) -> dict[str, Any]:
        cards = []
        if card:
            cards.append({"text": card, "style": "spec_badge", "in": 0.2, "out": 1.4})
        return {
            "shot_id": shot_id,
            "order": order,
            "duration_s": 2.0,
            "purpose": "展示产品",
            "visual": "柱塞泵在车间里。画面无任何文字、无 Logo、无价格、无电话号码。",
            "shot_size": "medium",
            "camera": "locked_off",
            "subject_refs": ["product:HP-300"],
            "scene_ref": "scene:workshop",
            "voiceover": spoken,
            "on_screen_text": cards,
            "transition_out": "cut",
            "generation_mode": "image_to_video",
            "status": "pending",
        }

    return {
        "script_id": "script-t16",
        "brief_id": "brief-t16",
        "language": "zh",
        "sections": [],
        "shots": [
            shot("S01", 1, "泵已经就位。", None),
            shot("S02", 2, "压力稳定。", "¥199"),
            shot("S03", 3, "欢迎了解交期。", None),
        ],
    }


def _brief() -> dict[str, Any]:
    return {
        "brief_id": "brief-t16",
        "raw_input": "给我们的泵做一条短片",
        "goal": "获客",
        "platform": ["抖音"],
        "duration_s": 15,
        "aspect_ratios": ["9:16"],
        "languages": ["zh"],
        "video_type": "product_showcase",
        "audience": "采购",
        "must_include": [],
        "style": "工业",
        "assumptions": [],
        "open_questions": [],
    }


def _brand() -> dict[str, Any]:
    return {
        "brand_id": "brand-t16",
        "company_name": "青岛示例机械",
        "industry": "manufacturing",
        "logo": {
            "primary": "oss://logo.png",
            "mono_white": "oss://logo-w.png",
            "safe_area_ratio": 0.2,
        },
        "colors": {"primary": "#0A3D91", "secondary": "#FFFFFF", "accent": "#F5A623"},
        "fonts": {"title": "NotoSansSC-Bold", "body": "NotoSansSC-Regular"},
        "products": [],
        "people": [
            {
                "person_id": "person-1",
                "role": "工程师",
                "photos": ["oss://face.png"],
                "consent": True,
                "voice_id": "clone-voice",
            }
        ],
        "voice": {"tts_voice": "zh_male_steady", "speed": 1.0},
        "tone": "专业",
        "banned_words": ["最好"],
        "cta": {"phone": "0532-88881234", "website": "https://example.com", "wechat_qr": ""},
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    import json

    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


def _plate(order: int) -> bytes:
    """A drawn swatch, not a customer photograph."""

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (64, 64), ((20 + order * 40) % 256, 64, 110))
    ImageDraw.Draw(image).rectangle((8, 8, 56, 56), outline=(250, 250, 250))
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


if __name__ == "__main__":
    main()
