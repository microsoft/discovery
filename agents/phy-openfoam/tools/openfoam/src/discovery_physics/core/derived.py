"""Physics-independent derived metrics: computed by code, never by the model."""

from __future__ import annotations

import math

from .models import Derived, Metric


def compute(derived: list[Derived], metrics: dict[str, Metric]) -> dict[str, Metric]:
    out: dict[str, Metric] = {}
    pool = dict(metrics)
    for d in derived:
        src = f"derived {d.op}({d.a}{', ' + d.b if d.b else ''})"

        def val(name: str | None) -> float | None:
            m = pool.get(name) if name else None
            if m is None or m.status != "measured" or isinstance(m.value, bool):
                return None
            return float(m.value) if isinstance(m.value, (int, float)) and math.isfinite(m.value) else None

        a, b = val(d.a), val(d.b)
        res: float | None = None
        if a is not None:
            if d.op == "scale":
                res = a * d.factor
            elif d.op == "abs_rel_error_pct" and d.reference not in (None, 0):
                res = abs(a / d.reference - 1) * 100
            elif b is not None and d.op == "difference":
                res = (a - b) * d.factor
            elif b is not None and d.op == "ratio" and b != 0:
                res = a / b * d.factor
        m = (Metric(value=res, unit=d.unit, source=src) if res is not None and math.isfinite(res)
             else Metric(value=None, unit=d.unit, source=src + ": operand missing/invalid", status="missing"))
        out[f"derived.{d.name}"] = m
        pool[f"derived.{d.name}"] = m
    return out
