"""N12 envelopes. Shots stay on the chapter 5 models.

``LicenseRecord`` is the only licence row. T20's delivery note uses the same
class. ``font`` and ``voice`` are the render-layer rows T20 adds; music and
sound effects stay ``music`` and ``sfx``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from workers.media.audio import AudioProvenance
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
    target_duration_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    intro_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    outro_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)


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
    provenance: AudioProvenance = "unknown"
    narration_path: str | None = None
    music_path: str | None = None
    sfx_path: str | None = None
    music_source_uri: str | None = None


class LicenseRecord(BaseModel):
    """One music or sound-effect use.

    T20 should copy ``source``, ``license``, ``evidence_ref``, ``expires_on``,
    and ``usage_scope`` into the delivery rights summary. A blank field means
    the piece cannot be delivered. ``expires_on`` is an ISO date, or ``none``
    when the licence does not expire.
    """

    record_id: str = Field(min_length=1)
    kind: Literal["music", "sfx", "font", "voice"]
    source: str = ""
    license: str = ""
    evidence_ref: str = ""
    expires_on: str = ""
    # ``none`` is the explicit perpetual mark. An empty value is missing and blocks.
    usage_scope: str = ""
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
    """Empty when every music and sound-effect row can be handed to T20."""

    for record in records:
        label = record.shot_id or record.record_id
        if not record.source.strip() or not record.license.strip():
            return f"{record.kind} {label} is missing a source or a license"
        if (
            not record.evidence_ref.strip()
            or not record.expires_on.strip()
            or not record.usage_scope.strip()
        ):
            return f"{record.kind} {label} is missing licence evidence, expiry, or usage scope"
    return ""
