"""Print the planted-defect interception rate. No live model call."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from workers.qa.calibrate import calibration_status
from workers.qa.samples import build_catalog
from workers.qa.scores import PASS_TOTAL
from workers.qa.service import review_shot
from workers.schemas.asset import QAReport


def build_report(directory: Path | None = None) -> dict[str, object]:
    folder = directory or Path(tempfile.mkdtemp(prefix="hilatv-t12-"))
    rows = build_catalog(folder)
    bad = hit = 0
    clean = clean_pass = 0
    video_deform = video_deform_hit = 0
    by_defect: dict[str, list[int]] = {}
    for row in rows:
        report = review_shot(
            {
                "project_id": "t12-accept",
                "shot_id": row.sample_id,
                "node": "n11_video" if row.kind == "video" else "n09_keyframe",
                "candidate_uri": str(row.path),
                "anchor_uri": str(row.anchor) if row.anchor else "",
                "expected_faces": row.expected_faces,
                "purpose": "产品特写",
                "visual": "金属块置于车间，画面没有文字",
                "shot_type": "slow_push_in",
            }
        )
        caught = _intercepted(report)
        if row.defect == "clean":
            clean += 1
            clean_pass += int(not caught)
            continue
        bad += 1
        hit += int(caught)
        bucket = by_defect.setdefault(row.defect, [0, 0])
        bucket[0] += 1
        bucket[1] += int(caught)
        if row.kind == "video" and row.defect == "product_deform":
            video_deform += 1
            video_deform_hit += int("product_deform" in report.hard_fail)
    rate = (hit / bad) if bad else 0.0
    calibration = calibration_status()
    return {
        "bad": bad,
        "intercepted": hit,
        "rate": round(rate, 4),
        "threshold": 0.9,
        "pass": rate >= 0.9 and clean_pass == clean and video_deform_hit == video_deform,
        "clean": clean,
        "clean_pass": clean_pass,
        "video_deform": video_deform,
        "video_deform_veto": video_deform_hit,
        "by_defect": {
            key: {"bad": value[0], "hit": value[1]} for key, value in sorted(by_defect.items())
        },
        "calibration": calibration["status"],
        "calibration_have": calibration["have"],
        "calibration_expected": calibration["expected"],
        "out": str(folder),
    }


def _intercepted(report: QAReport) -> bool:
    return bool(report.hard_fail) or report.total < PASS_TOTAL


def main() -> int:
    summary = build_report()
    print("HILATV_T12 " + json.dumps(summary, ensure_ascii=False))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
