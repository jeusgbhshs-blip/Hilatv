"""The requested whole-film time is distinct from its narration/story allocation."""

import copy
import json
from pathlib import Path

import pytest

from workers.nodes.n04_script.node import run as write_script
from workers.nodes.n04_script.qa import QAError as ScriptQAError
from workers.nodes.n04_script.qa import check as check_script
from workers.nodes.n05_storyboard.node import run as plan_storyboard
from workers.nodes.n05_storyboard.qa import QAError as BoardQAError
from workers.nodes.n05_storyboard.qa import check as check_board
from workers.qa.copycheck import count_units, target_units, within_target

FIXTURES = Path(__file__).resolve().parents[3] / "schemas" / "tests" / "fixtures"


@pytest.mark.parametrize("whole", [5, 6, 15, 30, 60])
def test_planning_reserves_packaging_without_relabeling_the_requested_total(gateway, whole):
    brief = json.loads((FIXTURES / "brief.json").read_text())
    brief.update(duration_s=whole, languages=["zh"])
    brand = json.loads((FIXTURES / "brand_kit.json").read_text())
    body = whole - min(2.4, max(0, whole - 4))
    scripted = write_script(
        {
            "project_id": "budget-plan",
            "payload": {
                "brief": brief,
                "brand_kit": brand,
                "story_duration_s": body,
            },
        },
        gateway=gateway,
    )
    script = check_script(scripted)
    units = sum(count_units(section.text, "zh") for section in script.sections)
    assert within_target(units, target_units(body, "zh"))
    assert scripted.payload["brief"]["duration_s"] == whole
    boarded = plan_storyboard(
        {
            "project_id": "budget-plan",
            "payload": {
                "brief": brief,
                "brand_kit": brand,
                "script": scripted.payload["script"],
                "story_duration_s": body,
            },
        },
        gateway=gateway,
    )
    board = check_board(boarded)
    assert sum(shot.duration_s for shot in board.shots) == pytest.approx(body, abs=0.001)
    assert boarded.payload["brief"]["duration_s"] == whole
    # Omitting/altering the saved allocation cannot silently validate this board
    # against a different time, and the existing 5% quality threshold remains.
    changed = copy.deepcopy(boarded)
    changed.payload["script"]["shots"][0]["duration_s"] += body * 0.06
    with pytest.raises(BoardQAError):
        check_board(changed)
    if whole == 15:
        without_allocation = copy.deepcopy(scripted)
        without_allocation.payload.pop("story_duration_s")
        with pytest.raises(ScriptQAError):
            check_script(without_allocation)
