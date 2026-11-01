"""Apply saved narration at the N6 consumption boundary without generating media.

Visual prompt suffixes remain separate and are consumed by explicit shot
regeneration. Narration is never copied into visual prompts.
"""

from __future__ import annotations

from typing import Any

from workers.expert.desk import load_doc
from workers.schemas.script import Script


def apply_saved_narration(project_id: str, script: dict[str, Any]) -> dict[str, Any]:
    result = Script.model_validate(script)
    desk = load_doc(project_id)
    for shot in result.shots:
        saved = desk.shots.get(shot.shot_id)
        if saved is not None and saved.narration is not None:
            shot.voiceover = saved.narration
    return result.model_dump(mode="json")
