"""T20 acceptance: every T17 export carries a visible and an implicit AI label.

OCR reads decoded frames. ffprobe reads the AIGC tag. No API key.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PIL import Image

from workers.compliance.label_measure import glyph_ink_height, minimum_glyph_px
from workers.compliance.metadata import content_producer, read_aigc
from workers.compliance.ocr import decode_frame_index, label_visible, recognize
from workers.nodes.n17_deliver.node import run
from workers.nodes.n17_deliver.qa import QAError
from workers.nodes.n17_deliver.sample import acceptance_request


def main() -> int:
    failures, stats = run_acceptance(Path("/tmp/hilatv-t20-accept"))
    if failures:
        print(f"T20 accept: FAIL {len(failures)}")
        for item in failures:
            print(f"[fail] {item}")
        return 1
    print(
        "T20 accept: "
        f"variants={stats['variants']} ocr={stats['ocr']} metadata={stats['metadata']} "
        f"input_reviews={stats['input_reviews']} output_reviews={stats['output_reviews']} "
        f"blocked={stats['blocked']}"
    )
    return 0


def run_acceptance(work: Path) -> tuple[list[str], dict[str, int]]:
    work.mkdir(parents=True, exist_ok=True)
    stats = {
        "variants": 0,
        "ocr": 0,
        "metadata": 0,
        "input_reviews": 0,
        "output_reviews": 0,
        "blocked": 0,
    }
    failures: list[str] = []
    try:
        _exports(work, stats)
        _blocked(work, stats)
    except Exception as exc:
        failures.append(str(exc))
    return failures, stats


def _exports(work: Path, stats: dict[str, int]) -> None:
    from workers.nodes.n17_deliver.support import build_gateway

    previous = os.environ.get("HILATV_PROJECT_DIR")
    os.environ["HILATV_PROJECT_DIR"] = str(work)
    try:
        gateway = build_gateway(work / "gateway")
        result = run(acceptance_request(work, project_id="accept-t20"), gateway=gateway)
    finally:
        if previous is None:
            os.environ.pop("HILATV_PROJECT_DIR", None)
        else:
            os.environ["HILATV_PROJECT_DIR"] = previous
    versions = result.payload["versions"]
    aspects = {item["aspect_ratio"] for item in versions}
    languages = {item["language"] for item in versions}
    if aspects != {"16:9", "9:16", "1:1"} or languages != {"zh", "en"}:
        raise AssertionError(f"variants aspects={sorted(aspects)} languages={sorted(languages)}")
    note = Path(result.payload["rights"]["materials_note"])
    if not note.is_file():
        raise AssertionError("materials note is missing")
    text = note.read_text(encoding="utf-8")
    for token in ("来源", "许可", "证明", "到期", "使用范围", "AI生成", "AIGC", "画面/声音未审"):
        if token not in text:
            raise AssertionError(f"materials note is missing {token}")
    for item in versions:
        stats["variants"] += 1
        path = Path(item["path"])
        meta = read_aigc(path)
        if meta.get("Label") != "1" or meta.get("ContentProducer") != content_producer():
            raise AssertionError(f"{path.name} metadata {meta}")
        if not meta.get("ProduceID") or not meta.get("ReservedCode1"):
            raise AssertionError(f"{path.name} is missing ProduceID or ReservedCode1")
        stats["metadata"] += 1
        if float(item["duration_s"]) + 1e-3 < 2:
            raise AssertionError(f"{path.name} is shorter than 2s")
        box = next(row for row in item["overlays"] if row["kind"] == "ai_label")
        if float(box["start_s"]) > 0 or float(box["end_s"]) - float(box["start_s"]) + 1e-3 < 2:
            raise AssertionError(f"{path.name} label is not on screen for 2s from the start")
        _label_on_frame(path, box, item, index=0)
        late = max(0, int(1.9 * 30))
        _label_on_frame(path, box, item, index=late)
        stats["ocr"] += 1
    logs = gateway.store.list_logs(project_id="accept-t20")
    for row in logs:
        if row["task"] != "content_safety":
            continue
        stage = row["params"].get("stage")
        if stage == "input":
            stats["input_reviews"] += 1
        elif stage == "output":
            stats["output_reviews"] += 1
    if stats["input_reviews"] < 1 or stats["output_reviews"] < 1:
        raise AssertionError(f"content safety stages {stats}")


def _label_on_frame(
    path: Path,
    box: dict[str, object],
    item: dict[str, object],
    *,
    index: int,
) -> None:
    with tempfile.TemporaryDirectory(prefix="hilatv-t20-frame-") as folder:
        frame_path = decode_frame_index(path, Path(folder) / "frame.png", index=index)
        image = Image.open(frame_path).convert("RGB")
        x, y, w, h = int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])
        crop = image.crop((x, y, min(image.width, x + w), min(image.height, y + h)))
        text = recognize(crop, psm="8")
        if not label_visible(text):
            text = recognize(crop, psm="13")
        if not label_visible(text):
            raise AssertionError(
                f"OCR missed AI生成 on {item['aspect_ratio']} {item['language']} "
                f"frame {index}: {text!r}"
            )
        if index == 0:
            ink = glyph_ink_height(crop)
            need = minimum_glyph_px(min(int(item["width"]), int(item["height"])))
            if ink < need:
                raise AssertionError(
                    f"{item['aspect_ratio']} glyph height {ink}px is under {need}px"
                )


def _blocked(work: Path, stats: dict[str, int]) -> None:
    from workers.nodes.n17_deliver.support import build_gateway

    previous = os.environ.get("HILATV_PROJECT_DIR")
    os.environ["HILATV_PROJECT_DIR"] = str(work)
    try:
        gateway = build_gateway(work / "gateway-block")
        raw = acceptance_request(
            work,
            project_id="blocked-t20",
            languages=["zh"],
            aspect_ratios=["16:9"],
            long_edge=160,
        )
        payload = raw["payload"]
        assert isinstance(payload, dict)
        brief = dict(payload["brief"])
        brief["raw_input"] = "HILATV_UNSAFE_SAMPLE 请做一条片子"
        payload["brief"] = brief
        try:
            run(raw, gateway=gateway)
        except QAError as exc:
            if "content safety" not in str(exc):
                raise
        else:
            raise AssertionError("unsafe input was delivered")
    finally:
        if previous is None:
            os.environ.pop("HILATV_PROJECT_DIR", None)
        else:
            os.environ["HILATV_PROJECT_DIR"] = previous
    stats["blocked"] += 1


if __name__ == "__main__":
    raise SystemExit(main())
