"""Dimensional parsing: a unit in the field name is not a unit on the number.

WHY THIS EXISTS
---------------
Budget targets were read with a regex that grabbed the first number in the
string and threw the rest away:

    def _num(v):
        m = re.search(r"[-+]?\\d+(\\.\\d+)?", str(v))
        return float(m.group(0)) if m else None

    area = _num(targets.get("area_um2") or targets.get("area"))

Measured consequences, all of which produced verdict `pass`:

    "12 mm2"   into area_um2 -> 12.0        (it is 12,000,000 um2 -- off by 1e6)
    "1.2 GHz"  into freq_mhz -> 1.2         (it is 1200 MHz      -- off by 1e3)
    "1e6 um2"                -> 1.0         (exponent silently discarded)
    "area of 2 blocks is 5000 um2" -> 2.0   (the WRONG number entirely)
    {"area": 12}             -> 12.0 um2    (no unit anywhere, unit asserted anyway)

A field called `area_um2` **records an intention, not a fact.** Nothing about
the name stops a value in mm2 being written into it, and a number wrong by a
factor of a million looks exactly like a number that is right: correct type,
correct field, and it propagates cleanly through every downstream calculation.
That is what makes this failure mode worth a gate rather than a warning.

WHAT THIS MODULE DOES
---------------------
Parses a value into an explicit (magnitude, unit) pair, converts to the field's
canonical unit, and REFUSES rather than guessing when the two cannot be
reconciled. Specifically it fails closed on:

  * a unit of the wrong DIMENSION for the field ("5 ns" into an area field)
  * a value carrying no unit in a field whose name carries none either
  * prose that does not begin with the quantity ("under 50 mW at 1.2 GHz")
  * trailing text that is not a recognised unit

Note that counting the numbers in the string is NOT a usable ambiguity test,
because legitimate units contain digits: "12 mm2" holds two digit-runs. The
magnitude is therefore anchored at the start and the entire remainder must
resolve to one recognised unit.

A bare number in a unit-suffixed field IS accepted -- `{"area_um2": 12000}` is
the normal, intended way to use the API -- but it is recorded as an ASSUMED
unit rather than an observed one, so a reader can tell the two apart.
"""

import re

# Canonical unit per dimension, and the factor to reach it. Frequency is
# canonicalised to MHz, area to um2, power to mW, time to ns -- matching the
# field-name suffixes the tool already publishes.
_DIMENSIONS = {
    "area": {"canonical": "um2", "units": {
        "um2": 1.0, "um^2": 1.0, "squm": 1.0,
        "nm2": 1e-6, "nm^2": 1e-6,
        "mm2": 1e6, "mm^2": 1e6,
        "cm2": 1e8, "cm^2": 1e8,
    }},
    "power": {"canonical": "mw", "units": {
        "mw": 1.0, "w": 1e3, "kw": 1e6, "uw": 1e-3, "nw": 1e-6, "pw": 1e-9,
    }},
    "frequency": {"canonical": "mhz", "units": {
        "mhz": 1.0, "hz": 1e-6, "khz": 1e-3, "ghz": 1e3, "thz": 1e6,
    }},
    "time": {"canonical": "ns", "units": {
        "ns": 1.0, "ps": 1e-3, "fs": 1e-6, "us": 1e3, "ms": 1e6, "s": 1e9,
    }},
    "voltage": {"canonical": "v", "units": {
        "v": 1.0, "mv": 1e-3, "uv": 1e-6, "kv": 1e3,
    }},
}

# Field-name suffix -> (dimension, unit the name CLAIMS). This is what lets the
# tool distinguish "the caller said um2" from "the tool assumed um2".
_FIELD_UNITS = {
    "area_um2": ("area", "um2"), "area_mm2": ("area", "mm2"),
    "power_mw": ("power", "mw"), "power_w": ("power", "w"),
    "leakage_mw": ("power", "mw"),
    "freq_mhz": ("frequency", "mhz"), "freq_ghz": ("frequency", "ghz"),
    "frequency_mhz": ("frequency", "mhz"),
    "period_ns": ("time", "ns"), "latency_ns": ("time", "ns"),
    "voltage_v": ("voltage", "v"),
}

# Bare aliases the tool accepts. They name a QUANTITY but assert no unit, so a
# value supplied under one MUST carry its own unit -- there is nothing to
# assume from.
_UNITLESS_ALIASES = {
    "area": "area", "power": "power", "frequency": "frequency",
    "freq": "frequency", "leakage": "power", "period": "time",
    "latency": "time", "voltage": "voltage",
}

_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


class UnitError(Exception):
    """A value that cannot be reconciled with its field. Never a warning."""


def _unit_dimension(unit):
    for dim, spec in _DIMENSIONS.items():
        if unit in spec["units"]:
            return dim
    return None


def convert(magnitude, from_unit, dimension):
    """Convert to the dimension's canonical unit. Raises on a foreign unit."""
    spec = _DIMENSIONS[dimension]
    if from_unit not in spec["units"]:
        raise UnitError("'%s' is not a %s unit" % (from_unit, dimension))
    return magnitude * spec["units"][from_unit]


def parse_quantity(value, field):
    """Resolve `value` for `field` into canonical units.

    Returns {value, unit, dimension, unit_source, declared}. `unit_source` is
    "explicit" when the value carried its own unit and "assumed_from_field_name"
    when the field name supplied it. Raises UnitError instead of guessing.
    """
    key = str(field).lower()
    if key in _FIELD_UNITS:
        dimension, field_unit = _FIELD_UNITS[key]
    elif key in _UNITLESS_ALIASES:
        dimension, field_unit = _UNITLESS_ALIASES[key], None
    else:
        raise UnitError("unknown target field '%s' -- refusing to guess its "
                        "dimension" % field)

    canonical = _DIMENSIONS[dimension]["canonical"]

    # A bare number: the ONLY case where the field name may supply the unit,
    # and only when the name actually states one.
    if isinstance(value, bool):
        raise UnitError("field '%s' got a boolean, not a quantity" % field)
    if isinstance(value, (int, float)):
        if field_unit is None:
            raise UnitError(
                "field '%s' names a quantity but no unit, and the value %r "
                "carries none either. There is nothing to convert from -- "
                "supply a unit-bearing field (e.g. '%s_%s') or a value like "
                "'%s %s'." % (field, value, key, canonical, value, canonical))
        return {"value": convert(float(value), field_unit, dimension),
                "unit": canonical, "dimension": dimension,
                "unit_source": "assumed_from_field_name",
                "declared": "%s %s" % (value, field_unit)}

    text = str(value).strip()
    if not text:
        raise UnitError("field '%s' is empty" % field)

    # The magnitude is ANCHORED at the start and the entire remainder must be a
    # single recognised unit. Scanning for a number anywhere was what let
    # "under 50 mW at 1.2 GHz" resolve to 50 for whichever field it landed in.
    # Note the unit itself may contain digits ("um2", "mm^2"), so counting
    # numbers in the string is not a usable ambiguity test.
    m = _NUMBER.match(text)
    if not m:
        raise UnitError(
            "field '%s' value %r does not start with a number. A target must be "
            "one quantity, written as '<number> <unit>'; prose is refused rather "
            "than scanned for whichever number appears first." % (field, text))
    magnitude = float(m.group(0))
    tail = text[m.end():].strip().lower()
    tail = re.sub(r"^[\s/]*", "", tail).replace(" ", "")

    if not tail:
        if field_unit is None:
            raise UnitError(
                "field '%s' value %r has no unit and the field name states "
                "none. Supply a unit." % (field, text))
        return {"value": convert(magnitude, field_unit, dimension),
                "unit": canonical, "dimension": dimension,
                "unit_source": "assumed_from_field_name",
                "declared": "%s %s" % (magnitude, field_unit)}

    found = _unit_dimension(tail)
    if found is None:
        raise UnitError("field '%s' value %r has unrecognised unit '%s'"
                        % (field, text, tail))
    # THE 1e6 CASE: a real unit, but of the wrong dimension for this field.
    if found != dimension:
        raise UnitError(
            "field '%s' expects a %s value but %r is a %s value ('%s'). A "
            "dimensional mismatch is refused rather than coerced."
            % (field, dimension, text, found, tail))

    converted = convert(magnitude, tail, dimension)
    out = {"value": converted, "unit": canonical, "dimension": dimension,
           "unit_source": "explicit", "declared": "%s %s" % (magnitude, tail)}
    # The quiet one: right dimension, wrong scale. "12 mm2" into area_um2 used
    # to record 12. It now records 12000000 and says the conversion happened.
    if field_unit is not None and tail != field_unit:
        out["converted_from"] = "%s %s" % (magnitude, tail)
        out["note"] = ("value was supplied in %s and converted to %s; the "
                       "field name claims %s, so the number as written was NOT "
                       "in the field's own unit." % (tail, canonical, field_unit))
    return out


def parse_targets(targets, aliases):
    """Parse a targets dict. Returns (values, findings).

    `aliases` maps a canonical output name to the accepted field names, in
    preference order, e.g. {"area_um2": ["area_um2", "area"]}. Every rejection
    is a finding; nothing is silently dropped, because a dropped target simply
    disappears from the budget instead of failing it.
    """
    values, findings = {}, []
    for out_name, candidates in aliases.items():
        for field in candidates:
            if field not in targets or targets[field] is None:
                continue
            try:
                q = parse_quantity(targets[field], field)
            except UnitError as exc:
                findings.append({"kind": "unit_error", "field": field,
                                 "severity": "gating", "detail": str(exc)})
            else:
                values[out_name] = q
                if q["unit_source"] == "assumed_from_field_name":
                    findings.append({
                        "kind": "unit_assumed", "field": field,
                        "severity": "advisory",
                        "detail": ("%r carried no unit; %s was taken from the "
                                   "field name. This is the normal way to call "
                                   "the API -- recorded so an assumed unit is "
                                   "distinguishable from an observed one."
                                   % (targets[field], q["unit"]))})
                elif "converted_from" in q:
                    findings.append({"kind": "unit_converted", "field": field,
                                     "severity": "advisory",
                                     "detail": q["note"]})
            break
    return values, findings
