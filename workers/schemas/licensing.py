"""Shared licence rows for the delivery note.

T21 (not on main) defines ``LicenseRecord`` / ``LicensingSummary`` on
``workers/nodes/n12_music/schema.py`` with ``kind``, ``source``, ``license``,
``title``, ``uri``, ``start_s``, ``duration_s``, ``shot_id``, and ``note``.
This model accepts that JSON. It also accepts ``type`` / ``licence`` and adds
the proof reference, expiry date, and usage scope the delivery note has to show.

A blank source or licence blocks delivery. An expiry date before today blocks
delivery. A missing proof reference does not, so a T21 music row can still ship.
推断: an omitted expiry means the grant does not expire.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class LicenseRecord(BaseModel):
    """One music, font, voice, or other third-party use."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    record_id: str = Field(min_length=1)
    kind: str = Field(min_length=1, validation_alias=AliasChoices("kind", "type"))
    source: str = ""
    license: str = Field(default="", validation_alias=AliasChoices("license", "licence"))
    title: str = ""
    uri: str = ""
    evidence_ref: str = Field(
        default="",
        validation_alias=AliasChoices("evidence_ref", "evidence", "proof"),
    )
    expires_on: date | None = None
    usage_scope: str = Field(
        default="",
        validation_alias=AliasChoices("usage_scope", "scope"),
    )
    start_s: float = Field(default=0, ge=0)
    duration_s: float = Field(default=0, ge=0)
    shot_id: str | None = None
    note: str = ""


class LicensingSummary(BaseModel):
    """What N12 (or a caller) hands to delivery. ``blocked`` follows the rows."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    project_id: str = Field(min_length=1)
    records: list[LicenseRecord] = Field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""


def today_shanghai(now: datetime | None = None) -> date:
    moment = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return moment.astimezone(ZoneInfo("Asia/Shanghai")).date()


def block_reason(records: list[LicenseRecord], *, today: date | None = None) -> str:
    """Empty when every row names a source and a licence and none are expired.

    ``today`` is inclusive: a grant that expires today can still be used.
    """

    current = today or today_shanghai()
    for record in records:
        label = record.shot_id or record.record_id
        if not record.source.strip() or not record.license.strip():
            return f"{record.kind} {label} is missing a source or a license"
        if record.expires_on is not None and record.expires_on < current:
            return f"{record.kind} {label} licence expired on {record.expires_on.isoformat()}"
    return ""


def summarize(
    project_id: str,
    records: list[LicenseRecord],
    *,
    today: date | None = None,
) -> LicensingSummary:
    reason = block_reason(records, today=today)
    return LicensingSummary(
        project_id=project_id,
        records=records,
        blocked=bool(reason),
        block_reason=reason,
    )


def parse_summary(raw: dict[str, Any] | None, *, project_id: str) -> LicensingSummary:
    if not raw:
        return summarize(project_id, [])
    data = dict(raw)
    data.setdefault("project_id", project_id)
    summary = LicensingSummary.model_validate(data)
    return summarize(summary.project_id or project_id, list(summary.records))
