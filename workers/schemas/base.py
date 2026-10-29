"""Shared JSON types for SPEC chapter 4 and 5 documents.

JSON numbers stay numbers and JSON booleans stay booleans. Strings are not
coerced, so ``duration_s="30"`` is rejected. Integers are accepted for float
fields because PostgreSQL jsonb stores ``1.0`` as ``1``.
"""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict


def json_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("must be a boolean")
    return value


def json_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("must be an integer")
    return value


def json_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("must be a finite number")
    return number


JsonBool = Annotated[bool, BeforeValidator(json_bool)]
JsonInt = Annotated[int, BeforeValidator(json_int)]
JsonFloat = Annotated[float, BeforeValidator(json_float)]

# N1–N18. SPEC examples use "N10", not "N01".
NODE_ID_PATTERN = r"^N(?:[1-9]|1[0-8])$"
ASPECT_RATIO_PATTERN = r"^\d+:\d+$"
LANGUAGE_PATTERN = r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$"
HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"


class SchemaModel(BaseModel):
    """Document base. Unknown keys are rejected. Dumps use field aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)

    def model_dump_json(self, **kwargs: Any) -> str:
        kwargs.setdefault("by_alias", True)
        return super().model_dump_json(**kwargs)
