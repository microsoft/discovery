"""CPU-only evidence validators; NumPy is the only non-standard dependency.

Invalid configuration and independent-calculation inputs raise ValueError.
Comparisons/audits return JSON-native verdicts, never inferred measurements.
"""

import numpy as np

__all__ = ["compare_numeric", "independent_kinetic_energy",
           "independent_energy_drift", "audit_hook_events"]


def _result(status, reason, evidence):
    return {"status": status, "reason": reason, "evidence": evidence}


def _real_array(value, name):
    array = np.asarray(value)
    if np.ma.isMaskedArray(value) or array.dtype.kind not in "iuf":
        raise ValueError(f"{name} must contain unmasked real numbers (not booleans)")
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains non-finite data")
    return array


def _float64(value, name):
    with np.errstate(over="ignore", invalid="ignore"):
        array = _real_array(value, name).astype(np.float64)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} is outside the float64 range")
    return array


def _integers(value, name, minimum):
    array = np.asarray(value)
    if (np.ma.isMaskedArray(value) or array.dtype.kind not in "iu"
            or np.any(array < minimum)):
        raise ValueError(f"{name} must contain integers >= {minimum}; no coercion")
    return array


def _integer_scalar(value, name, minimum=0):
    array = _integers(value, name, minimum)
    if array.ndim != 0:
        raise ValueError(f"{name} must be scalar")
    return int(array)


def _label(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("labels must be nonempty strings")
    return str(value)


def compare_numeric(observed, reference, *, observed_source, reference_source, atol, rtol):
    """Use abs(observed-reference) <= atol + rtol*abs(reference), elementwise.

    No broadcasting, NaN equality, masking, or string/object/complex coercion.
    Tolerances are finite nonnegative real scalars (not booleans). Computation
    uses at least float64; integer/integer differences are formed exactly.
    Mixed integer/float inputs that would round integers fail closed, as does
    arithmetic overflow. max_rel uses abs(reference): 0/0 is 0; an unbounded or
    unrepresentable maximum is None with max_rel_nonfinite=True. Uncomputed
    discrepancies remain None. count is the number of shape-matched elements.
    Distinct labels and non-aliasing cannot prove logical independence: copied
    or fabricated references require external provenance review.
    """
    tolerances = {}
    for name, value in (("atol", atol), ("rtol", rtol)):
        scalar = _float64(value, name)
        if scalar.ndim != 0 or scalar < 0:
            raise ValueError(f"{name} must be a nonnegative real scalar")
        tolerances[name] = float(scalar)
    evidence = dict(tolerances, observed_source=None, reference_source=None,
                    observed_shape=None, reference_shape=None, observed_dtype=None,
                    reference_dtype=None, count=0, max_abs=None, max_rel=None,
                    max_rel_nonfinite=False, mismatch_count=None)
    try:
        labels = [_label(v).strip() for v in (observed_source, reference_source)]
        evidence.update(observed_source=labels[0], reference_source=labels[1])
        if labels[0] == labels[1]:
            raise ValueError("provenance labels must be distinct")
    except ValueError as exc:
        return _result("unverified", str(exc), evidence)
    if observed is None or reference is None:
        return _result("unverified", "missing observed or reference data", evidence)
    if observed is reference:
        return _result("unverified", "same input object", evidence)
    try:
        a, b = np.asarray(observed), np.asarray(reference)
        for name, array in (("observed", a), ("reference", b)):
            evidence.update({f"{name}_shape": list(array.shape),
                             f"{name}_dtype": str(array.dtype)})
        if np.shares_memory(a, b):
            return _result("unverified", "inputs share memory", evidence)
        if (any(np.ma.isMaskedArray(v) for v in (observed, reference))
                or any(x is None for v in (a, b) if v.dtype.kind == "O" for x in v.flat)):
            return _result("unverified", "missing or masked data", evidence)
        if a.shape != b.shape:
            return _result("fail", "shapes differ; broadcasting is forbidden", evidence)
        evidence["count"] = int(a.size)
        _real_array(a, "observed")
        _real_array(b, "reference")
        if not a.size:
            return _result("unexercised", "zero eligible elements", evidence)
        dtype = np.result_type(a.dtype, b.dtype, np.float64)
        x, y = a.astype(dtype), b.astype(dtype)
        both_integer = a.dtype.kind in "iu" and b.dtype.kind in "iu"
        if not both_integer:
            for raw, cast in ((a, x), (b, y)):
                if raw.dtype.kind in "iu" and np.any(raw.astype(object) != cast.astype(object)):
                    raise ValueError("integer values lose precision during comparison")
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            delta = (np.abs(a.astype(object) - b.astype(object)).astype(dtype)
                     if both_integer else np.abs(x - y))
            limit = tolerances["atol"] + tolerances["rtol"] * np.abs(y)
            if not np.isfinite(delta).all() or not np.isfinite(limit).all():
                raise ValueError("comparison arithmetic overflow")
            relative = np.divide(delta, np.abs(y), out=np.zeros_like(delta), where=y != 0)
            relative = np.where((y == 0) & (delta != 0), np.inf, relative)
        max_abs, max_rel = float(delta.max()), float(relative.max())
        mismatches = int(np.count_nonzero(delta > limit))
        evidence.update(max_abs=max_abs if np.isfinite(max_abs) else None,
                        max_rel=max_rel if np.isfinite(max_rel) else None,
                        max_rel_nonfinite=not bool(np.isfinite(max_rel)),
                        mismatch_count=mismatches)
        return _result("fail" if mismatches else "pass",
                       "outside tolerance" if mismatches else "within tolerance", evidence)
    except (TypeError, ValueError, OverflowError) as exc:
        return _result("fail", str(exc), evidence)


def independent_kinetic_energy(velocities, masses, graph_indices, num_graphs):
    """Return float64 direct sums of 0.5*m*sum(v*v), in caller-supplied units.

    Shapes: velocities (N, 3), masses (N,), integer graph_indices (N,).
    num_graphs is a positive integer scalar. Empty graphs have zero energy.
    No toolkit helpers or unit conversions; non-finite arithmetic is rejected.
    """
    v, m = _float64(velocities, "velocities"), _float64(masses, "masses")
    g = _integers(graph_indices, "graph_indices", 0)
    size = _integer_scalar(num_graphs, "num_graphs", 1)
    if size > np.iinfo(np.intp).max:
        raise ValueError("num_graphs exceeds index range")
    if v.ndim != 2 or v.shape[1] != 3 or m.shape != (v.shape[0],) or g.shape != m.shape:
        raise ValueError("expected velocities (N,3), masses (N,), graph_indices (N,)")
    if np.any(m <= 0) or np.any(g >= size):
        raise ValueError("masses must be positive and graph indices in range")
    result = np.zeros(size, dtype=np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        np.add.at(result, g.astype(np.intp), 0.5 * m * np.sum(v * v, axis=1))
    return _float64(result, "kinetic energy result")


def independent_energy_drift(total, reference, num_atoms, step_count, metric="per_atom_per_step"):
    """Return abs(total-reference)/(num_atoms*max(step_count,1)), or absolute.

    Energies must be matching scalars or 1-D arrays. Integer atom counts (>0)
    and step counts (>=0) must be scalar or exactly the energy shape; integral
    floats and booleans are rejected. Counts are validated for both metrics.
    None reference means first-reference capture and returns None, never zero.
    Inputs other than that absent reference are still validated in this case.
    """
    if not isinstance(metric, str) or metric not in ("per_atom_per_step", "absolute"):
        raise ValueError("unknown drift metric")
    energy = _float64(total, "total")
    atoms, steps = _integers(num_atoms, "num_atoms", 1), _integers(step_count, "step_count", 0)
    if energy.ndim > 1 or any(a.shape not in ((), energy.shape) for a in (atoms, steps)):
        raise ValueError("energies must be scalar/1-D; counts must be scalar or match")
    if reference is None:
        return None
    ref = _float64(reference, "reference")
    if energy.shape != ref.shape:
        raise ValueError("energy and reference shapes differ")
    with np.errstate(over="ignore", invalid="ignore"):
        result = np.abs(energy - ref)
        if metric == "per_atom_per_step":
            result = result / (atoms.astype(np.float64) * np.maximum(steps, 1).astype(np.float64))
    return _float64(result, "energy drift result")


def _entry(counter, stage, hook):
    return (_integer_scalar(counter, "step_counter"), _label(stage), _label(hook))


def audit_hook_events(events, expected_entries):
    """Audit measured dicts, in supplied order, against (counter, stage, hook) tuples.

    Required keys: sequence, event ('entry'/'return'), invocation_id,
    step_counter, stage, hook_type. Sequence numbers are nonnegative integers,
    strictly increasing (gaps allowed). Invocation IDs are nonempty strings or
    nonnegative integers, unique per hook type and paired once. Pair metadata
    must match, including optional instance_id. Nested calls are allowed.
    Counts describe structurally valid records and matched pairs, not inferred
    calls. Empty/None traces are unverified even when the expectation is empty.
    Trace authenticity, like numeric provenance, needs external review.
    """
    if not isinstance(expected_entries, (list, tuple)):
        raise ValueError("expected_entries must be a list of triples")
    expected = []
    for item in expected_entries:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ValueError("expected entries must be (step_counter, stage, hook_type)")
        expected.append(list(_entry(*item)))
    evidence = dict(event_count=0, entry_count=0, return_count=0, pair_count=0,
                    by_hook={}, actual_entries=[], expected_entries=expected, errors=[])
    if events is None or isinstance(events, (list, tuple)) and not events:
        return _result("unverified", "no measured events", evidence)
    if not isinstance(events, (list, tuple)):
        return _result("fail", "events must be a list of measured dictionaries", evidence)
    evidence["event_count"] = len(events)
    errors, seen, returned, previous = evidence["errors"], {}, set(), -1
    for index, event in enumerate(events):
        try:
            if not isinstance(event, dict):
                raise ValueError("event must be a dictionary")
            sequence = _integer_scalar(event["sequence"], "sequence")
            kind = event["event"]
            if not isinstance(kind, str) or kind not in ("entry", "return"):
                raise ValueError("event must be entry or return")
            entry = _entry(event["step_counter"], event["stage"], event["hook_type"])
            invocation = event["invocation_id"]
            invocation = (_label(invocation) if isinstance(invocation, str)
                          else _integer_scalar(invocation, "invocation_id"))
            instance = event.get("instance_id")
            if "instance_id" in event:
                instance = _label(instance)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            errors.append(f"event {index}: {exc}")
            continue
        if sequence <= previous:
            errors.append(f"event {index}: sequence must be strictly increasing and unique")
        previous = sequence
        counts = evidence["by_hook"].setdefault(entry[2], {"entry": 0, "return": 0, "pairs": 0})
        counts[kind] += 1
        evidence[f"{kind}_count"] += 1
        key, metadata = (entry[2], invocation), (entry, instance)
        if kind == "entry":
            evidence["actual_entries"].append(list(entry))
            if key in seen:
                errors.append(f"event {index}: duplicate invocation entry")
            else:
                seen[key] = metadata
        elif key not in seen or key in returned or seen[key] != metadata:
            errors.append(f"event {index}: unpaired, duplicate, or mismatched return")
        else:
            returned.add(key)
            counts["pairs"] += 1
            evidence["pair_count"] += 1
    if seen.keys() - returned:
        errors.append("missing returns")
    if evidence["actual_entries"] != expected:
        errors.append("full entry order differs from expected_entries")
    return _result("fail" if errors else "pass",
                   "; ".join(errors) if errors else "measured order and pairs match", evidence)