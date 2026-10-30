"""T22 interception report. Mock judge and ASR only. Live picture scores stay 未测."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image

from workers.nodes.n16_final_review.node import run
from workers.nodes.n16_final_review.support import brand_elements, request_for, write_film
from workers.qa.samples import Sample, _plate, build_catalog
from workers.workflow.store import project_path


def build_report(gateway: object, directory: Path) -> dict[str, object]:
    catalog = directory / "catalog"
    rows = build_catalog(catalog)
    bad = hit = 0
    clean = clean_ok = 0
    visual_passes = 0
    video_deform = video_deform_hit = 0
    by_defect: dict[str, list[int]] = {}
    for index, sample in enumerate(rows):
        project_id = f"t22{index:03d}"
        body = _review_sample(gateway, project_id, sample)
        codes = [item["code"] for item in body["issues"] if item["kind"] == "hard_flaw"]
        located = all(
            item["shot_id"] == sample.sample_id
            for item in body["issues"]
            if item["kind"] == "hard_flaw"
        )
        visual_passes += int(body["visual_reviewed"] is True)
        if sample.defect == "clean":
            clean += 1
            clean_ok += int(
                not codes
                and body["release"] is True
                and body["decisions"] == []
                and body["visual_reviewed"] is False
            )
            continue
        bad += 1
        caught = located and bool(codes) and _caught(sample.defect, codes)
        hit += int(caught)
        bucket = by_defect.setdefault(sample.defect, [0, 0])
        bucket[0] += 1
        bucket[1] += int(caught)
        if sample.kind == "video" and sample.defect == "product_deform":
            video_deform += 1
            video_deform_hit += int("product_deform" in codes and located)
    rate = (hit / bad) if bad else 0.0
    logo = _flag(gateway, "t22logo", logo=False, code="missing_logo")
    cta = _flag(gateway, "t22cta", cta=False, code="missing_cta")
    passed = (
        bad > 0
        and rate >= 0.9
        and clean_ok == clean
        and clean > 0
        and video_deform_hit == video_deform
        and video_deform > 0
        and visual_passes == 0
        and logo
        and cta
    )
    return {
        "bad": bad,
        "intercepted": hit,
        "rate": round(rate, 4),
        "threshold": 0.9,
        "pass": passed,
        "clean": clean,
        "clean_pass": clean_ok,
        "visual_passes": visual_passes,
        "video_deform": video_deform,
        "video_deform_veto": video_deform_hit,
        "missing_logo_flagged": logo,
        "missing_cta_flagged": cta,
        "vlm_live": "未测",
        "asr_heard": "未测",
        "by_defect": {
            key: {"bad": value[0], "hit": value[1]} for key, value in sorted(by_defect.items())
        },
    }


def _review_sample(gateway: object, project_id: str, sample: Sample) -> dict:
    film = _film_for(project_id, sample)
    seconds = 2.0 if sample.kind == "video" else 1.0
    anchors = {sample.sample_id: str(sample.anchor)} if sample.anchor else {}
    faces = {sample.sample_id: sample.expected_faces}
    raw = request_for(
        project_id,
        film,
        [sample.sample_id],
        seconds_each=seconds,
        anchors=anchors,
        faces=faces,
    )
    return run(raw, gateway=gateway).payload


def _film_for(project_id: str, sample: Sample) -> Path:
    if sample.kind == "video":
        dest = project_path(project_id, create=True) / "film.mp4"
        shutil.copy(sample.path, dest)
        return dest
    with Image.open(sample.path) as image:
        frame = image.convert("RGB")
    return write_film(project_id, [frame])


def _flag(
    gateway: object,
    project_id: str,
    *,
    logo: bool = True,
    cta: bool = True,
    code: str,
) -> bool:
    film = write_film(project_id, [_plate("rect")])
    raw = request_for(
        project_id,
        film,
        ["S01"],
        seconds_each=1.0,
        elements=brand_elements(logo=logo, cta=cta),
    )
    body = run(raw, gateway=gateway).payload
    flagged = any(item["code"] == code for item in body["issues"])
    return flagged and body["release"] is False and body["decisions"] == []


def _caught(defect: str, hard_fail: list[str]) -> bool:
    found = set(hard_fail)
    if defect in found:
        return True
    text = {"extra_text", "garbled_text"}
    return defect in text and bool(found & text)


def main() -> int:
    os.environ["HILATV_LIVE"] = "0"
    os.environ.setdefault("HILATV_BUDGET_CNY", "0")
    os.environ.setdefault("HILATV_DAILY_BUDGET_CNY", "0")
    root = Path(os.environ.get("HILATV_PROJECT_DIR") or tempfile.mkdtemp(prefix="hilatv-t22-"))
    root.mkdir(parents=True, exist_ok=True)
    os.environ["HILATV_PROJECT_DIR"] = str(root)
    from gateway.service import get_gateway, reset_gateway

    reset_gateway()
    summary = build_report(get_gateway(), root)
    print("HILATV_T22 " + json.dumps(summary, ensure_ascii=False))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
