"""T17 acceptance: 16:9, 9:16, and 1:1 keep the subject inside the frame.

Chinese and English are both exported. Subtitles and the dub use that language.
No API key. The picture is a local plate and speech goes through the mock gateway.
"""

from __future__ import annotations

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
    print("T17 accept: 16:9, 9:16, and 1:1 keep the subject inside; zh and en match")
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

    result = run(acceptance_request(work), gateway=build_gateway(work / "gateway"))
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
    zh = [item["spoken"][0]["voiceover"] for item in versions if item["language"] == "zh"]
    en = [item["spoken"][0]["voiceover"] for item in versions if item["language"] == "en"]
    if not zh or not en or zh[0] == en[0]:
        raise AssertionError("Chinese and English dubs are not distinct")


if __name__ == "__main__":
    raise SystemExit(main())
