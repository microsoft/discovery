"""Inject the monitors acceptance depends on. Output formatting only; numerics untouched."""

from __future__ import annotations

import re

from ..core.models import Diagnostics
from .foamio import set_dict_entry

LIB = '"libfieldFunctionObjects.so"'
FORCES_LIB = '"libforces.so"'
SAMPLING_LIB = '"libsampling.so"'
_LIBS = {"forces": FORCES_LIB, "forceCoeffs": FORCES_LIB, "probes": SAMPLING_LIB}
_SETTING_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_SETTING_VALUE = re.compile(r"^[A-Za-z0-9_.+\-() eE]{1,512}$")


def _per_step(name: str, body: str, lib: str = LIB) -> str:
    return (f"    {name}\n    {{\n        libs ({lib});\n        {body}\n"
            "        writeControl timeStep;\n        writeInterval 1;\n"
            "        writeFields false;\n        log false;\n    }\n")


def monitor_block(d: Diagnostics) -> str:
    parts: list[str] = []
    if d.mass_balance or d.inlet or d.outlet or d.impermeable_patches:
        for patch in d.patches:
            parts.append(_per_step(f"flux_{patch}",
                                   f"type surfaceFieldValue; select patch; patch {patch}; "
                                   "operation sum; fields (phi);"))
    if d.mass_balance:
        parts.append(_per_step("domain_mass", "type volFieldValue; cellZone all; "
                                              "operation volIntegrate; fields (rho);"))
    positive = [f.name for f in d.fields if f.positive and f.components == 1]
    if positive:
        parts.append(_per_step("extrema", "type volFieldValue; cellZone all; operation min; "
                                          f"fields ({' '.join(positive)});"))
    for q in d.quantities:
        settings = []
        for key, value in q.settings.items():
            if not _SETTING_KEY.match(key) or not _SETTING_VALUE.match(value) or key in {
                "type", "libs", "writeControl", "writeInterval", "functionObjectLibs"
            }:
                raise ValueError(f"quantity {q.name}: setting {key!r} is not allowed")
            settings.append(f"{key} {value};")
        parts.append(_per_step(f"q_{q.name}", f"type {q.function}; " + " ".join(settings),
                               _LIBS.get(q.function, LIB)))
    return "functions\n{\n" + "".join(parts) + "}\n"


def time_precision(end_time: float | None) -> int:
    """Significant digits for time names.

    Monitors stamp rows with time names, so closure needs many digits (12 digits still gave
    3e-9 closure on the forward step, 10 digits 3e-7). But Foundation aborts when a time name
    would need more than 18 digits; adaptive steps with a few integer digits hit that at 15-17.
    Keep fractional resolution near 1e-14 while leaving headroom below the abort limit.
    """
    import math

    whole = max(1, int(math.floor(math.log10(end_time))) + 1) if end_time and end_time >= 1 else 0
    return max(12, min(15, 15 - whole))


def instrument_control_dict(text: str, d: Diagnostics) -> str:
    """Pin auditable output and append monitors; the safety gate forbids user `functions`."""
    text = re.sub(r"(?m)^// \*{5,}.*$", "", text)
    m = re.search(r"(?m)^\s*endTime\s+([^;\s]+)\s*;", text)
    end = float(m.group(1)) if m else None
    end = max(end or 0.0, d.target_time)
    for key, value in (("writeFormat", "ascii"), ("writeCompression", "off"),
                       ("writePrecision", "17"), ("timePrecision", str(time_precision(end))),
                       ("runTimeModifiable", "false")):
        text = set_dict_entry(text, key, value)
    return text.rstrip() + "\n\n" + monitor_block(d)


def set_end_time(text: str, end_time: float, restart: bool) -> str:
    text = set_dict_entry(text, "endTime", repr(float(end_time)))
    if restart:
        text = set_dict_entry(text, "startFrom", "latestTime")
    return text
