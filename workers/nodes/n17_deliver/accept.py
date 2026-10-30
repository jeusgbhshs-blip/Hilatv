"""T17 acceptance: 16:9, 9:16, and 1:1 keep the subject inside the frame.

Chinese and English are both exported. Subtitles and the dub use that language.
No API key. The picture is a local plate and speech goes through the mock gateway.
"""

from __future__ import annotations

import os
from pathlib import Path

from workers.nodes.n17_deliver.node import run
from workers.nodes.n17_deliver.sample import acceptance_request


def main() -> int:
    failures = run_acceptance(Path("/tmp/hilatv-t17-accept"))
    if failures:
        print(f"T17 accept: FAIL {len(failures)}")
        for item in failures:
            print(f"[fail] {item}")
        return 1
    print(
        "T17 accept: 16:9, 9:16, and 1:1 keep the subject inside; zh and en match; "
        "heard-dub check: not verified in mock"
    )
    return 0


def run_acceptance(work: Path) -> list[str]:
    work.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    try:
        _case(work)
    except Exception as exc:
        failures.append(str(exc))
    return failures


def _case(work: Path) -> None:
    from workers.nodes.n17_deliver.support import build_gateway

    previous = os.environ.get("HILATV_PROJECT_DIR")
    os.environ["HILATV_PROJECT_DIR"] = str(work)
    try:
        result = run(acceptance_request(work), gateway=build_gateway(work / "gateway"))
    finally:
        if previous is None:
            os.environ.pop("HILATV_PROJECT_DIR", None)
        else:
            os.environ["HILATV_PROJECT_DIR"] = previous
    versions = result.payload["versions"]
    aspects = {item["aspect_ratio"] for item in versions}
    languages = {item["language"] for item in versions}
    if aspects != {"16:9", "9:16", "1:1"}:
        raise AssertionError(f"aspects {sorted(aspects)}")
    if languages != {"zh", "en"}:
        raise AssertionError(f"languages {sorted(languages)}")
    modes = {mode for item in versions for mode in item["modes"].values()}
    if "crop" not in modes or "blur" not in modes:
        raise AssertionError(f"expected crop and blur, got {sorted(modes)}")
    if any(
        item["qa_status"] != "pass" or item["subject_box_source"] != "provided" for item in versions
    ):
        raise AssertionError("measured boxes should be a QA pass")
    zh = [item for item in versions if item["language"] == "zh"]
    en = [item for item in versions if item["language"] == "en"]
    if not zh or not en or zh[0]["spoken"][0]["voiceover"] == en[0]["spoken"][0]["voiceover"]:
        raise AssertionError("Chinese and English dubs are not distinct")
    for item in versions:
        if not any(
            box["kind"] == "ai_label" and box["text"] == "AI生成" for box in item["overlays"]
        ):
            raise AssertionError(f"{item['aspect_ratio']} {item['language']} is missing AI生成")
        for line in item["spoken"]:
            _heard(item["language"], line)


def _heard(language: str, line: dict[str, str]) -> None:
    if line.get("heard_check") != "not_verified_in_mock":
        raise AssertionError("mock export must not claim a verified hearing")
    if line.get("transcript", "").strip():
        raise AssertionError("mock ASR echo was stored as a transcript")
    if language == "zh":
        if not _cjk(line["subtitle"]):
            raise AssertionError("Chinese subtitles have no Chinese")
        return
    if not _latin(line["subtitle"]):
        raise AssertionError("English subtitles have no Latin text")


def _cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _latin(text: str) -> bool:
    return any("a" <= char.lower() <= "z" for char in text)


if __name__ == "__main__":
    raise SystemExit(main())
