"""CNY amounts as exact decimals (6 places)."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

_QUANT = Decimal("0.000001")


def money(value: object) -> Decimal:
    if isinstance(value, Decimal):
        amount = value
    elif value is None or value == "":
        amount = Decimal("0")
    else:
        amount = Decimal(str(value))
    return amount.quantize(_QUANT, rounding=ROUND_HALF_UP)


def money_upper(value: object) -> Decimal:
    """Never round a reservation below its non-negative verified upper bound."""
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid cost upper bound")
    return amount.quantize(_QUANT, rounding=ROUND_CEILING)
