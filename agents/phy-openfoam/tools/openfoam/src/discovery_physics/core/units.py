"""Small explicit multiplicative-unit algebra; never convert measured numbers.

Unknown labels support same-label arithmetic only. Prefix changes require an
explicit numeric scale and factor unit. Offset temperatures are not supported.
This is dimensional consistency, not proof of a quantity's physical meaning.
"""

from __future__ import annotations

import math
import re

from .models import Derived

# Dimensions: mass, length, time, absolute temperature.
_BASE = {
    "1": ((0, 0, 0, 0), 1.0), "%": ((0, 0, 0, 0), 0.01),
    "percent": ((0, 0, 0, 0), 0.01), "kg": ((1, 0, 0, 0), 1.0),
    "g": ((1, 0, 0, 0), 0.001), "m": ((0, 1, 0, 0), 1.0),
    "mm": ((0, 1, 0, 0), 0.001), "cm": ((0, 1, 0, 0), 0.01),
    "s": ((0, 0, 1, 0), 1.0), "K": ((0, 0, 0, 1), 1.0),
    "N": ((1, 1, -2, 0), 1.0), "Pa": ((1, -1, -2, 0), 1.0),
    "kPa": ((1, -1, -2, 0), 1000.0), "MPa": ((1, -1, -2, 0), 1e6),
    "J": ((1, 2, -2, 0), 1.0), "W": ((1, 2, -3, 0), 1.0),
    "Hz": ((0, 0, -1, 0), 1.0),
}
_TOKEN = re.compile(r"([A-Za-z%]+|1)(?:\^?(-?\d+))?$")
_OPAQUE = re.compile(r"[A-Za-z_][A-Za-z0-9_:-]*$")
_AFFINE = {"degC", "Celsius", "°C", "degF", "°F"}


def signature(unit: str) -> tuple[tuple[int, ...], float] | None:
    """Return dimensions and SI multiplier, or None for an opaque label."""
    if not unit.strip():
        raise ValueError("unit label must not be blank")
    if unit in _AFFINE:
        raise ValueError("offset temperature units require explicit conversion to K before arithmetic")
    expression = unit.replace("·", "*").replace(".", "*").replace(" ", "*")
    parts = re.split(r"([*/])", expression)
    dimensions, scale, sign = [0, 0, 0, 0], 1.0, 1
    for i, token in enumerate(parts):
        if i % 2:
            sign = -1 if token == "/" else 1
            continue
        match = _TOKEN.fullmatch(token)
        if not match or match[1] not in _BASE:
            if len(parts) == 1 and _OPAQUE.fullmatch(unit):
                return None
            raise ValueError(f"unsupported or malformed unit expression {unit!r}")
        power = int(match[2] or 1) * sign
        if abs(power) > 16:
            raise ValueError("unit exponent exceeds supported bounds")
        dims, multiplier = _BASE[match[1]]
        dimensions = [old + power * new for old, new in zip(dimensions, dims)]
        scale *= multiplier**power
    if not math.isfinite(scale) or scale == 0:
        raise ValueError("invalid unit multiplier")
    return tuple(dimensions), scale


def same(a: str, b: str) -> bool:
    first, second = signature(a), signature(b)
    return a == b or (first is not None and second is not None and first[0] == second[0]
                      and math.isclose(first[1], second[1], rel_tol=1e-12))


def validate(d: Derived, units: dict[str, str]) -> None:
    """Require operand compatibility and an honest output label before arithmetic."""
    if d.a not in units or (d.op in {"difference", "ratio"} and d.b not in units):
        raise ValueError("operand unit is missing")
    a = units[d.a]
    b = units[d.b] if d.b in units else None
    # Validate labels even on identity/opaque operations.
    for unit in (a, b, d.unit, d.factor_unit, d.reference_unit):
        if unit is not None:
            signature(unit)
    if d.op == "abs_rel_error_pct":
        if d.reference in (None, 0) or not same(d.reference_unit or a, a):
            raise ValueError("reference must be nonzero and in the operand's unit")
        if d.unit not in {"%", "percent"} or d.factor != 1 or d.factor_unit != "1":
            raise ValueError("relative error output must be percent with no additional factor")
        return
    if d.reference is not None or d.reference_unit is not None:
        raise ValueError("reference units/values apply only to relative reference errors")
    if d.op == "difference" and not same(a, b):
        raise ValueError(f"difference operand units differ: {a!r} and {b!r}; convert explicitly first")
    first, second, factor, output = signature(a), signature(b) if b else None, signature(d.factor_unit), signature(d.unit)
    if d.op in {"scale", "difference"}:
        if d.factor_unit == "1" and same(a, d.unit):
            return
        result = first
    else:
        if same(a, b):
            result = _BASE["1"]
        elif first is not None and second is not None:
            result = (tuple(x - y for x, y in zip(first[0], second[0])), first[1] / second[1])
        else:
            raise ValueError("ratio of opaque unequal unit labels is unsupported")
    if result is None or factor is None or output is None:
        raise ValueError("dimensional conversion requires supported explicit multiplicative units")
    expected = (tuple(x + y for x, y in zip(result[0], factor[0])), result[1] * factor[1])
    if expected[0] != output[0] or not math.isclose(expected[1], output[1], rel_tol=1e-12):
        raise ValueError(f"output unit {d.unit!r} does not match operands and factor unit {d.factor_unit!r}")