"""Commercial licenses the render layer is allowed to use.

A caller flag such as ``licensed: true`` is not a record. The name has to
match an entry below.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LicenseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    license_id: str
    kind: str
    name: str
    holder: str
    commercial: bool
    uri: str


class LicenseError(Exception):
    """The asset has no commercial license on file."""


_FONTS: tuple[LicenseRecord, ...] = (
    LicenseRecord(
        license_id="ofl-noto-sans-sc-regular",
        kind="font",
        name="NotoSansSC-Regular.otf",
        holder="Adobe and the Noto CJK project",
        commercial=True,
        uri="templates/packaging/fonts/NotoSansSC-Regular.otf",
    ),
    LicenseRecord(
        license_id="ofl-noto-sans-sc-bold",
        kind="font",
        name="NotoSansSC-Bold.otf",
        holder="Adobe and the Noto CJK project",
        commercial=True,
        uri="templates/packaging/fonts/NotoSansSC-Bold.otf",
    ),
)


def lookup_license(name: str, kind: str) -> LicenseRecord | None:
    for record in _FONTS:
        if record.name == name and record.kind == kind and record.commercial is True:
            return record
    return None


def require_license(name: str, kind: str) -> LicenseRecord:
    found = lookup_license(name, kind)
    if found is None:
        raise LicenseError(f"缺少可商用授权：{kind} {name}")
    return found
