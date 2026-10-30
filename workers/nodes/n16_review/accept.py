"""T20 acceptance: every T17 export carries a visible and an implicit AI label.

OCR reads decoded frames. ffprobe reads the AIGC tag. No API key.
"""

from __future__ import annotations

import os
from pathlib import Path

from workers.compliance.metadata import read_aigc
from workers.compliance.ocr import label_visible, read_label
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
    for token in ("来源", "许可", "证明", "到期", "使用范围", "AI生成", "AIGC"):
        if token not in text:
            raise AssertionError(f"materials note is missing {token}")
    for item in versions:
        stats["variants"] += 1
        path = Path(item["path"])
        meta = read_aigc(path)
        if meta.get("Label") != "1" or meta.get("ContentProducer") != "HiLatv":
            raise AssertionError(f"{path.name} metadata {meta}")
        stats["metadata"] += 1
        box = next(row for row in item["overlays"] if row["kind"] == "ai_label")
        found = read_label(
            path,
            box=(int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])),
            at_s=0.2,
        )
        if not label_visible(found):
            raise AssertionError(
                f"OCR missed AI生成 on {item['aspect_ratio']} {item['language']}: {found!r}"
            )
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
