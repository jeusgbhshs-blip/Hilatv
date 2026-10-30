"""Load the fixed 60-brief benchmark (SPEC chapter 9: 10 per industry)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from workers.schemas.brand import Industry

CASE_COUNT = 60
PER_INDUSTRY = 10

INDUSTRY_ORDER: tuple[str, ...] = tuple(item.value for item in Industry)

_BRIEFS = Path(__file__).resolve().parent / "briefs"


@dataclass(frozen=True)
class Case:
    case_id: str
    industry: str
    sentence: str
    source: str


def briefs_dir() -> Path:
    return _BRIEFS


def load_cases(root: Path | None = None) -> list[Case]:
    directory = root or _BRIEFS
    cases: list[Case] = []
    seen: set[str] = set()
    files = sorted(path for path in directory.glob("*.yaml") if path.is_file())
    if not files:
        raise ValueError(f"no benchmark briefs in {directory}")
    for path in files:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError(f"{path.name} must be a mapping")
        industry = str(document.get("industry") or "")
        if industry not in INDUSTRY_ORDER:
            raise ValueError(f"{path.name} industry {industry} is not one of the six")
        rows = document.get("cases")
        if not isinstance(rows, list):
            raise ValueError(f"{path.name} is missing cases")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{path.name} has a case that is not a mapping")
            case_id = str(row.get("id") or "").strip()
            sentence = str(row.get("sentence") or "").strip()
            if not case_id or not sentence:
                raise ValueError(f"{path.name} has a case without id or sentence")
            if case_id in seen:
                raise ValueError(f"duplicate case id {case_id}")
            seen.add(case_id)
            cases.append(
                Case(case_id=case_id, industry=industry, sentence=sentence, source=path.name)
            )
    _check_shape(cases)
    return cases


def _check_shape(cases: list[Case]) -> None:
    if len(cases) != CASE_COUNT:
        raise ValueError(f"benchmark has {len(cases)} cases, expected {CASE_COUNT}")
    counts = {industry: 0 for industry in INDUSTRY_ORDER}
    for case in cases:
        counts[case.industry] += 1
    bad = [f"{name}={count}" for name, count in counts.items() if count != PER_INDUSTRY]
    if bad:
        raise ValueError("each industry needs 10 cases: " + ", ".join(bad))


def project_id_for(case_id: str) -> str:
    """Id that also fits the workflow project-id pattern."""

    return f"e18-{case_id}"
