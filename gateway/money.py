"""CNY amounts as exact decimals (6 places)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_QUANT = Decimal("0.000001")


def money(value: object) -> Decimal:
    if isinstance(value, Decimal):
        amount = value
    elif value is None or value == "":
        amount = Decimal("0")
    else:
        amount = Decimal(str(value))
    return amount.quantize(_QUANT, rounding=ROUND_HALF_UP)
