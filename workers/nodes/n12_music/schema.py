"""N12 envelopes. Shots stay on the chapter 5 models.

``LicenseRecord`` is the handoff for T20's licensing summary. T20 is not on
main, so this task defines the record here instead of writing into N17.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from workers.nodes.n06_voiceover.schema import ShotVoiceover
from workers.schemas.brief import Brief
from workers.schemas.script import Script


class NodeRequest(BaseModel):
    project_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    shot_id: str | None = None
    attempt: int = Field(default=1, ge=1, le=5)


class NodeResult(BaseModel):
    project_id: str
    node: str
    ok: bool
    payload: dict[str, Any]
    attempt: int


class N12Input(BaseModel):
    """Storyboard plus optional N6 takes. Mood selects the test-library track."""

    script: Script
    voiceovers: list[ShotVoiceover] = Field(default_factory=list)
    brief: Brief | None = None
    mood: str = ""
    work_dir: str | None = None


class CutPoint(BaseModel):
    shot_id: str
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)


class AudioTrack(BaseModel):
    """Soundtrack N15 can drop onto the timeline. ``start_s`` null means 'at the shots'."""

    path: str = Field(min_length=1)
    start_s: float | None = None
    duration_s: float = Field(gt=0)
    source: str = Field(min_length=1)
    license: str = Field(min_length=1)


class LicenseRecord(BaseModel):
    """One music or sound-effect use.

    T20 should copy ``source`` and ``license`` into the delivery rights summary.
    A blank ``source`` or ``license`` means the piece cannot be delivered.
    """

    record_id: str = Field(min_length=1)
    kind: Literal["music", "sfx"]
    source: str = ""
    license: str = ""
    title: str = ""
    uri: str = ""
    start_s: float = Field(default=0, ge=0)
    duration_s: float = Field(default=0, ge=0)
    shot_id: str | None = None
    note: str = ""


class LicensingSummary(BaseModel):
    """Bundle N12 hands to T20. ``blocked`` is false only when every record is complete."""

    project_id: str
    records: list[LicenseRecord]
    blocked: bool = False
    block_reason: str = ""


def incomplete_reason(records: list[LicenseRecord]) -> str:
    """Empty when every music and sound-effect row names a source and a license."""

    for record in records:
        if not record.source.strip() or not record.license.strip():
            label = record.shot_id or record.record_id
            return f"{record.kind} {label} is missing a source or a license"
    return ""
