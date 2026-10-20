"""Bounded direct-Clarabel hidden-flow support solver.

The returned vectors and residuals are numerical certificate evidence to the
declared tolerances. They are not a formal proof.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Iterator

import clarabel
import numpy as np
import scipy
from scipy import linalg, sparse

SCHEMA_VERSION = 1
ADAPTER_VERSION = "1.0.0"
MAXIMUM_INPUT_BYTES = 16 * 1024 * 1024
MAXIMUM_RESULT_BYTES = 16 * 1024 * 1024
MAXIMUM_BATCH_REQUESTS = 64
MAXIMUM_BATCH_INPUT_BYTES = 32 * 1024 * 1024
MAXIMUM_BATCH_RESULT_BYTES = 64 * 1024 * 1024
MAXIMUM_COEFFICIENTS = 96
MAXIMUM_OBSERVATIONS = 256
MAXIMUM_MATRIX_ENTRIES = 96 * 96
MAXIMUM_OBSERVATION_MATRIX_ENTRIES = MAXIMUM_OBSERVATIONS * MAXIMUM_COEFFICIENTS
MAXIMUM_CANONICAL_MATRIX_ENTRIES = 70_000
MAXIMUM_IDENTIFIER_LENGTH = 64
MAXIMUM_REQUEST_IDENTIFIER_LENGTH = 128
MAXIMUM_ITERATIONS = 100_000
MAXIMUM_NUMERIC_MAGNITUDE = 1e100
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REQUEST_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REQUEST_KEYS = {
    "schemaVersion",
    "requestId",
    "problemId",
    "coefficientCount",
    "observationMatrix",
    "lowerBounds",
    "upperBounds",
    "energyMatrix",
    "energyBudget",
    "roughnessMatrix",
    "roughnessBudget",
    "objective",
    "rankRelativeTolerance",
    "solverSettings",
}
_SETTINGS_KEYS = {
    "maximumIterations",
    "absoluteGapTolerance",
    "relativeGapTolerance",
    "feasibilityTolerance",
    "infeasibilityTolerance",
    "presolveEnabled",
    "equilibrationEnabled",
    "iterativeRefinementEnabled",
    "maximumThreads",
}
_MATRIX_KEYS = {"rows", "columns", "values"}
_NATIVE_STATUSES = {
    "Unsolved",
    "Solved",
    "PrimalInfeasible",
    "DualInfeasible",
    "AlmostSolved",
    "AlmostPrimalInfeasible",
    "AlmostDualInfeasible",
    "MaxIterations",
    "MaxTime",
    "NumericalError",
    "InsufficientProgress",
    "CallbackTerminated",
}


class HiddenFlowInputError(ValueError):
    """Raised when a request violates the bounded adapter contract."""


@dataclass(frozen=True)
class MatrixData:
    rows: int
    columns: int
    values: tuple[float, ...]


@dataclass(frozen=True)
class ValidatedRequest:
    request_id: str
    problem_id: str
    coefficient_count: int
    observation_matrix: MatrixData
    lower_bounds: tuple[float, ...]
    upper_bounds: tuple[float, ...]
    energy_matrix: MatrixData
    energy_budget: float | None
    roughness_matrix: MatrixData
    roughness_budget: float | None
    objective: tuple[float, ...]
    rank_relative_tolerance: float
    solver_settings: dict[str, Any]


@dataclass(frozen=True)
class CanonicalProblem:
    q: np.ndarray
    a: np.ndarray
    b: np.ndarray
    cones: tuple[dict[str, Any], ...]
    clarabel_cones: tuple[Any, ...]
    energy_factor: np.ndarray | None
    roughness_factor: np.ndarray | None

    def as_json(self) -> dict[str, Any]:
        return {
            "q": _vector_json(self.q),
            "a": _matrix_json(self.a),
            "b": _vector_json(self.b),
            "cones": list(self.cones),
            "energyFactor": (
                None
                if self.energy_factor is None
                else _matrix_json(self.energy_factor)
            ),
            "roughnessFactor": (
                None
                if self.roughness_factor is None
                else _matrix_json(self.roughness_factor)
            ),
        }


def _reject_constant(value: str) -> None:
    raise HiddenFlowInputError(f"non-finite JSON token {value!r} is not allowed")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HiddenFlowInputError(f"duplicate JSON property {key!r} is not allowed")
        result[key] = value
    return result


def load_request_bytes(raw: bytes) -> ValidatedRequest:
    """Decode and validate a request before creating NumPy/SciPy arrays."""

    if len(raw) > MAXIMUM_INPUT_BYTES:
        raise HiddenFlowInputError("input exceeds the 16 MiB byte limit")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise HiddenFlowInputError("input must be valid UTF-8") from error
    try:
        value = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except json.JSONDecodeError as error:
        raise HiddenFlowInputError(
            f"input is not valid JSON at line {error.lineno}, column {error.colno}"
        ) from error
    except HiddenFlowInputError:
        raise
    except ValueError as error:
        raise HiddenFlowInputError("input contains an invalid JSON value") from error
    except RecursionError as error:
        raise HiddenFlowInputError("input JSON nesting is too deep") from error
    return validate_request(value)


def _object(value: Any, path: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise HiddenFlowInputError(f"{path} must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise HiddenFlowInputError(f"{path} is missing {missing[0]!r}")
    if unknown:
        raise HiddenFlowInputError(f"{path} contains unknown key {unknown[0]!r}")


def _integer(value: Any, path: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise HiddenFlowInputError(
            f"{path} must be an integer between {minimum} and {maximum}"
        )
    return value


def _finite(value: Any, path: str) -> float:
    if type(value) not in (int, float):
        raise HiddenFlowInputError(f"{path} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise HiddenFlowInputError(f"{path} must be a finite number")
    if abs(parsed) > MAXIMUM_NUMERIC_MAGNITUDE:
        raise HiddenFlowInputError(
            f"{path} exceeds the supported numerical magnitude"
        )
    return parsed


def _positive(value: Any, path: str, maximum: float = 1.0) -> float:
    parsed = _finite(value, path)
    if parsed <= 0.0 or parsed > maximum:
        raise HiddenFlowInputError(f"{path} must be greater than zero and <= {maximum}")
    return parsed


def _optional_budget(value: Any, path: str) -> float | None:
    if value is None:
        return None
    parsed = _finite(value, path)
    if parsed < 0.0:
        raise HiddenFlowInputError(f"{path} must be nonnegative or null")
    return parsed


def _identifier(value: Any, path: str) -> str:
    if (
        type(value) is not str
        or len(value) > MAXIMUM_IDENTIFIER_LENGTH
        or _IDENTIFIER.fullmatch(value) is None
    ):
        raise HiddenFlowInputError(f"{path} must be a portable identifier")
    return value


def _request_identifier(value: Any, path: str) -> str:
    if (
        type(value) is not str
        or len(value) > MAXIMUM_REQUEST_IDENTIFIER_LENGTH
        or _REQUEST_IDENTIFIER.fullmatch(value) is None
    ):
        raise HiddenFlowInputError(
            f"{path} must be a portable request identifier"
        )
    return value


def _boolean(value: Any, path: str) -> bool:
    if type(value) is not bool:
        raise HiddenFlowInputError(f"{path} must be a boolean")
    return value


def _finite_vector(value: Any, path: str, expected_length: int) -> tuple[float, ...]:
    if type(value) is not list or len(value) != expected_length:
        raise HiddenFlowInputError(
            f"{path} must contain exactly {expected_length} values"
        )
    return tuple(_finite(item, f"{path}[{index}]") for index, item in enumerate(value))


def _matrix(
    value: Any,
    path: str,
    expected_rows: int | None = None,
    expected_columns: int | None = None,
    maximum_entries: int = MAXIMUM_MATRIX_ENTRIES,
) -> MatrixData:
    item = _object(value, path)
    _exact_keys(item, _MATRIX_KEYS, path)
    rows = _integer(item["rows"], f"{path}.rows", 0, MAXIMUM_OBSERVATIONS)
    columns = _integer(
        item["columns"], f"{path}.columns", 0, MAXIMUM_COEFFICIENTS
    )
    if expected_rows is not None and rows != expected_rows:
        raise HiddenFlowInputError(f"{path}.rows must equal {expected_rows}")
    if expected_columns is not None and columns != expected_columns:
        raise HiddenFlowInputError(f"{path}.columns must equal {expected_columns}")
    entry_count = rows * columns
    if entry_count > maximum_entries:
        raise HiddenFlowInputError(
            f"{path} exceeds the {maximum_entries}-entry limit"
        )
    values = _finite_vector(item["values"], f"{path}.values", entry_count)
    return MatrixData(rows=rows, columns=columns, values=values)


def validate_request(value: Any) -> ValidatedRequest:
    item = _object(value, "$")
    _exact_keys(item, _REQUEST_KEYS, "$")
    if item["schemaVersion"] != SCHEMA_VERSION:
        raise HiddenFlowInputError("$.schemaVersion must equal 1")

    coefficient_count = _integer(
        item["coefficientCount"],
        "$.coefficientCount",
        1,
        MAXIMUM_COEFFICIENTS,
    )
    observation = _matrix(
        item["observationMatrix"],
        "$.observationMatrix",
        expected_columns=coefficient_count,
        maximum_entries=MAXIMUM_OBSERVATION_MATRIX_ENTRIES,
    )
    lower = _finite_vector(
        item["lowerBounds"], "$.lowerBounds", observation.rows
    )
    upper = _finite_vector(
        item["upperBounds"], "$.upperBounds", observation.rows
    )
    for index, (lower_value, upper_value) in enumerate(zip(lower, upper)):
        if lower_value > upper_value:
            raise HiddenFlowInputError(
                f"$.lowerBounds[{index}] must not exceed $.upperBounds[{index}]"
            )

    energy = _matrix(
        item["energyMatrix"],
        "$.energyMatrix",
        expected_rows=coefficient_count,
        expected_columns=coefficient_count,
    )
    roughness = _matrix(
        item["roughnessMatrix"],
        "$.roughnessMatrix",
        expected_rows=coefficient_count,
        expected_columns=coefficient_count,
    )
    settings = _object(item["solverSettings"], "$.solverSettings")
    _exact_keys(settings, _SETTINGS_KEYS, "$.solverSettings")
    validated_settings = {
        "maximumIterations": _integer(
            settings["maximumIterations"],
            "$.solverSettings.maximumIterations",
            1,
            MAXIMUM_ITERATIONS,
        ),
        "absoluteGapTolerance": _positive(
            settings["absoluteGapTolerance"],
            "$.solverSettings.absoluteGapTolerance",
        ),
        "relativeGapTolerance": _positive(
            settings["relativeGapTolerance"],
            "$.solverSettings.relativeGapTolerance",
        ),
        "feasibilityTolerance": _positive(
            settings["feasibilityTolerance"],
            "$.solverSettings.feasibilityTolerance",
        ),
        "infeasibilityTolerance": _positive(
            settings["infeasibilityTolerance"],
            "$.solverSettings.infeasibilityTolerance",
        ),
        "presolveEnabled": _boolean(
            settings["presolveEnabled"], "$.solverSettings.presolveEnabled"
        ),
        "equilibrationEnabled": _boolean(
            settings["equilibrationEnabled"],
            "$.solverSettings.equilibrationEnabled",
        ),
        "iterativeRefinementEnabled": _boolean(
            settings["iterativeRefinementEnabled"],
            "$.solverSettings.iterativeRefinementEnabled",
        ),
        "maximumThreads": _integer(
            settings["maximumThreads"],
            "$.solverSettings.maximumThreads",
            1,
            1,
        ),
    }

    return ValidatedRequest(
        request_id=_request_identifier(item["requestId"], "$.requestId"),
        problem_id=_identifier(item["problemId"], "$.problemId"),
        coefficient_count=coefficient_count,
        observation_matrix=observation,
        lower_bounds=lower,
        upper_bounds=upper,
        energy_matrix=energy,
        energy_budget=_optional_budget(item["energyBudget"], "$.energyBudget"),
        roughness_matrix=roughness,
        roughness_budget=_optional_budget(
            item["roughnessBudget"], "$.roughnessBudget"
        ),
        objective=_finite_vector(
            item["objective"], "$.objective", coefficient_count
        ),
        rank_relative_tolerance=_positive(
            item["rankRelativeTolerance"], "$.rankRelativeTolerance"
        ),
        solver_settings=validated_settings,
    )


def _numpy_matrix(matrix: MatrixData) -> np.ndarray:
    return np.asarray(matrix.values, dtype=np.float64).reshape(
        matrix.rows, matrix.columns
    )


def _normalize_vector_signs(vectors: np.ndarray) -> np.ndarray:
    result = np.array(vectors, dtype=np.float64, copy=True)
    if result.ndim != 2:
        return result
    for column in range(result.shape[1]):
        vector = result[:, column]
        if vector.size == 0:
            continue
        pivot = int(np.argmax(np.abs(vector)))
        if vector[pivot] < 0.0:
            result[:, column] *= -1.0
    result[result == 0.0] = 0.0
    return result


def _svd_diagnostics(
    observation: np.ndarray, relative_tolerance: float
) -> dict[str, Any]:
    coefficient_count = observation.shape[1]
    _, singular_values, vh = np.linalg.svd(observation, full_matrices=True)
    maximum = float(singular_values[0]) if singular_values.size else 0.0
    threshold = max(
        relative_tolerance * maximum,
        128.0 * np.finfo(np.float64).eps * max(maximum, 1.0),
    )
    rank = int(np.count_nonzero(singular_values > threshold))
    nullity = coefficient_count - rank
    null_basis = _normalize_vector_signs(vh[rank:, :].T)
    condition = (
        None
        if rank == 0
        else _finite_or_none(maximum / float(singular_values[rank - 1]))
    )
    return {
        "singularValues": _vector_json(singular_values),
        "rank": rank,
        "nullity": nullity,
        "threshold": _finite_float(threshold, "SVD threshold"),
        "conditionEstimate": condition,
        "nullSpaceBasis": _matrix_json(null_basis),
    }


def _psd_factor(matrix: np.ndarray, label: str) -> np.ndarray:
    scale = max(float(np.max(np.abs(matrix), initial=0.0)), 1.0)
    symmetry_tolerance = 1024.0 * np.finfo(np.float64).eps * scale
    if float(np.max(np.abs(matrix - matrix.T), initial=0.0)) > symmetry_tolerance:
        raise HiddenFlowInputError(f"{label} must be symmetric")
    symmetric = (matrix + matrix.T) * 0.5
    eigenvalues, eigenvectors = linalg.eigh(
        symmetric, check_finite=False, driver="evd"
    )
    eigenvalue_scale = max(
        float(np.max(np.abs(eigenvalues), initial=0.0)), 1.0
    )
    psd_tolerance = 1024.0 * np.finfo(np.float64).eps * eigenvalue_scale
    minimum_eigenvalue = (
        float(eigenvalues[0]) if eigenvalues.size > 0 else 0.0
    )
    if minimum_eigenvalue < -psd_tolerance:
        raise HiddenFlowInputError(f"{label} must be positive semidefinite")
    if minimum_eigenvalue > psd_tolerance:
        factor = linalg.cholesky(
            symmetric,
            lower=False,
            check_finite=False,
            overwrite_a=False,
        )
        factor[factor == 0.0] = 0.0
        return factor
    eigenvalues = np.maximum(eigenvalues, 0.0)
    eigenvectors = _normalize_vector_signs(eigenvectors)
    factor = np.sqrt(eigenvalues)[:, None] * eigenvectors.T
    factor[factor == 0.0] = 0.0
    return factor


def _append_rows(
    row_blocks: list[np.ndarray],
    b_blocks: list[np.ndarray],
    cone_records: list[dict[str, Any]],
    clarabel_cones: list[Any],
    rows: np.ndarray,
    values: Iterable[float],
    cone_type: str,
    label: str,
) -> None:
    dimension = rows.shape[0]
    if dimension == 0:
        return
    row_blocks.append(rows)
    b_blocks.append(np.asarray(tuple(values), dtype=np.float64))
    cone_records.append({"type": cone_type, "dimension": dimension, "label": label})
    if cone_type == "zero":
        clarabel_cones.append(clarabel.ZeroConeT(dimension))
    elif cone_type == "nonnegative":
        clarabel_cones.append(clarabel.NonnegativeConeT(dimension))
    else:
        clarabel_cones.append(clarabel.SecondOrderConeT(dimension))


def _canonicalize(request: ValidatedRequest) -> CanonicalProblem:
    count = request.coefficient_count
    exact_count = sum(
        1
        for lower, upper in zip(request.lower_bounds, request.upper_bounds)
        if lower == upper
    )
    band_count = request.observation_matrix.rows - exact_count
    canonical_rows = exact_count + 2 * band_count
    if request.energy_budget is not None:
        canonical_rows += count + 1
    if request.roughness_budget is not None:
        canonical_rows += count + 1
    canonical_entries = canonical_rows * count
    if canonical_entries > MAXIMUM_CANONICAL_MATRIX_ENTRIES:
        raise HiddenFlowInputError(
            "canonical conic matrix exceeds the "
            f"{MAXIMUM_CANONICAL_MATRIX_ENTRIES}-entry limit"
        )

    observation = _numpy_matrix(request.observation_matrix)
    lower = np.asarray(request.lower_bounds, dtype=np.float64)
    upper = np.asarray(request.upper_bounds, dtype=np.float64)
    objective = np.asarray(request.objective, dtype=np.float64)

    exact_mask = lower == upper
    band_mask = ~exact_mask
    row_blocks: list[np.ndarray] = []
    b_blocks: list[np.ndarray] = []
    cone_records: list[dict[str, Any]] = []
    clarabel_cones: list[Any] = []

    _append_rows(
        row_blocks,
        b_blocks,
        cone_records,
        clarabel_cones,
        observation[exact_mask],
        upper[exact_mask],
        "zero",
        "observation-exact",
    )
    _append_rows(
        row_blocks,
        b_blocks,
        cone_records,
        clarabel_cones,
        observation[band_mask],
        upper[band_mask],
        "nonnegative",
        "observation-upper",
    )
    _append_rows(
        row_blocks,
        b_blocks,
        cone_records,
        clarabel_cones,
        -observation[band_mask],
        -lower[band_mask],
        "nonnegative",
        "observation-lower",
    )

    factors: list[np.ndarray | None] = []
    for matrix_data, budget, label in (
        (request.energy_matrix, request.energy_budget, "energy"),
        (request.roughness_matrix, request.roughness_budget, "roughness"),
    ):
        if budget is None:
            factors.append(None)
            continue
        factor = _psd_factor(_numpy_matrix(matrix_data), f"$.{label}Matrix")
        factors.append(factor)
        # With Ax+s=b, A=[0; F] and b=[budget; 0] expose
        # s=[budget; -F x] in the second-order cone.
        soc_rows = np.vstack((np.zeros((1, count)), factor))
        soc_b = np.concatenate(([budget], np.zeros(factor.shape[0])))
        _append_rows(
            row_blocks,
            b_blocks,
            cone_records,
            clarabel_cones,
            soc_rows,
            soc_b,
            "second-order",
            f"{label}-budget",
        )

    a = np.vstack(row_blocks) if row_blocks else np.zeros((0, count))
    b = np.concatenate(b_blocks) if b_blocks else np.zeros(0)
    a[a == 0.0] = 0.0
    b[b == 0.0] = 0.0
    q = -objective
    q[q == 0.0] = 0.0
    return CanonicalProblem(
        q=q,
        a=a,
        b=b,
        cones=tuple(cone_records),
        clarabel_cones=tuple(clarabel_cones),
        energy_factor=factors[0],
        roughness_factor=factors[1],
    )


def _clarabel_settings(request: ValidatedRequest) -> Any:
    source = request.solver_settings
    settings = clarabel.DefaultSettings()
    settings.verbose = False
    settings.max_iter = source["maximumIterations"]
    settings.tol_gap_abs = source["absoluteGapTolerance"]
    settings.tol_gap_rel = source["relativeGapTolerance"]
    settings.tol_feas = source["feasibilityTolerance"]
    settings.tol_infeas_abs = source["infeasibilityTolerance"]
    settings.tol_infeas_rel = source["infeasibilityTolerance"]
    settings.presolve_enable = source["presolveEnabled"]
    settings.equilibrate_enable = source["equilibrationEnabled"]
    settings.iterative_refinement_enable = source["iterativeRefinementEnabled"]
    settings.max_threads = 1
    settings.direct_solve_method = "qdldl"
    return settings


def _finite_float(value: Any, label: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RuntimeError(f"Clarabel returned non-finite {label}")
    if parsed == 0.0:
        return 0.0
    return parsed


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def _vector_json(values: Iterable[Any]) -> list[float]:
    result: list[float] = []
    for index, value in enumerate(values):
        result.append(_finite_float(value, f"vector value {index}"))
    return result


def _matrix_json(matrix: np.ndarray) -> dict[str, Any]:
    rows, columns = matrix.shape
    return {
        "rows": int(rows),
        "columns": int(columns),
        "values": _vector_json(matrix.reshape(-1)),
    }


def _linear_solver_metadata(info: Any) -> str | None:
    linear_solver = getattr(info, "linsolver", None)
    if linear_solver is None:
        return None
    name = getattr(linear_solver, "name", None)
    if name is None:
        return None
    return (
        f"{name};direct={str(bool(getattr(linear_solver, 'direct', False))).lower()}"
        f";threads={int(getattr(linear_solver, 'threads', 0))}"
        f";nnzA={int(getattr(linear_solver, 'nnzA', 0))}"
        f";nnzL={int(getattr(linear_solver, 'nnzL', 0))}"
    )


def _solver_identity(linear_solver: str | None) -> dict[str, Any]:
    return {
        "adapter": "flowblind-hidden-flow-direct-clarabel",
        "adapterVersion": ADAPTER_VERSION,
        "pythonVersion": platform.python_version(),
        "clarabelVersion": clarabel.__version__,
        "scipyVersion": scipy.__version__,
        "numpyVersion": np.__version__,
        "image": os.environ.get("FLOWBLIND_SOLVER_IMAGE"),
        "architecture": platform.machine(),
        "linearSolver": linear_solver,
    }


def solve_request(request: ValidatedRequest, raw_input: bytes) -> dict[str, Any]:
    observation = _numpy_matrix(request.observation_matrix)
    svd = _svd_diagnostics(observation, request.rank_relative_tolerance)
    canonical = _canonicalize(request)
    canonical_value = canonical.as_json()
    canonical_sha = canonical_json_sha256(canonical_value)
    warnings: list[str] = []

    objective_scale = float(np.max(np.abs(canonical.q), initial=0.0))
    zero_threshold = 128.0 * np.finfo(np.float64).eps * max(
        objective_scale, 1.0
    )
    if objective_scale <= zero_threshold:
        warnings.append(
            "Degenerate objective: the objective is numerically zero at the "
            "adapter threshold; Clarabel solved feasibility only."
        )
    solver = clarabel.DefaultSolver(
        sparse.csc_matrix((request.coefficient_count, request.coefficient_count)),
        canonical.q,
        sparse.csc_matrix(canonical.a),
        canonical.b,
        list(canonical.clarabel_cones),
        _clarabel_settings(request),
    )
    native_solution = solver.solve()
    info = solver.get_info()
    native_status = str(native_solution.status)
    status = native_status if native_status in _NATIVE_STATUSES else "Unknown"
    if status == "Unknown":
        warnings.append(f"Clarabel returned unknown native status {native_status!r}.")
    solution = {
        "status": status,
        "coefficients": _vector_json(native_solution.x),
        "slacks": _vector_json(native_solution.s),
        "dual": _vector_json(native_solution.z),
        "primalObjective": _finite_or_none(native_solution.obj_val),
        "dualObjective": _finite_or_none(native_solution.obj_val_dual),
        "iterations": int(native_solution.iterations),
        "reportedPrimalResidual": _finite_or_none(info.res_primal),
        "reportedDualResidual": _finite_or_none(info.res_dual),
        "reportedAbsoluteGap": _finite_or_none(info.gap_abs),
        "reportedRelativeGap": _finite_or_none(info.gap_rel),
    }
    linear_solver = _linear_solver_metadata(info)

    return {
        "schemaVersion": SCHEMA_VERSION,
        "requestId": request.request_id,
        "requestSha256": hashlib.sha256(raw_input).hexdigest(),
        "canonicalSha256": canonical_sha,
        "solver": _solver_identity(linear_solver),
        "settings": request.solver_settings,
        "svd": svd,
        "canonicalization": canonical_value,
        "solution": solution,
        "warnings": warnings,
    }


def _javascript_number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError("canonical JSON accepts only finite numbers")
    if value == 0.0:
        return "0"
    representation = repr(value).lower()
    absolute = abs(value)
    if 1e-6 <= absolute < 1e21:
        fixed = format(Decimal(representation), "f")
        if "." in fixed:
            fixed = fixed.rstrip("0").rstrip(".")
        return fixed

    if "e" not in representation:
        decimal_value = Decimal(representation)
        exponent = decimal_value.adjusted()
        digits = "".join(str(digit) for digit in decimal_value.as_tuple().digits)
        digits = digits.rstrip("0")
        mantissa = digits[0]
        if len(digits) > 1:
            mantissa += "." + digits[1:]
        if value < 0.0:
            mantissa = "-" + mantissa
    else:
        mantissa, exponent_text = representation.split("e", 1)
        if mantissa.endswith(".0"):
            mantissa = mantissa[:-2]
        exponent = int(exponent_text)
    exponent_sign = "+" if exponent >= 0 else ""
    return f"{mantissa}e{exponent_sign}{exponent}"


def _canonical_text_chunks(
    value: Any, level: int, prefix: str = ""
) -> Iterator[str]:
    indent = "  " * level
    line_prefix = indent + prefix
    if value is None:
        yield line_prefix + "null"
        return
    if value is True:
        yield line_prefix + "true"
        return
    if value is False:
        yield line_prefix + "false"
        return
    if type(value) is int:
        yield line_prefix + str(value)
        return
    if type(value) is float:
        yield line_prefix + _javascript_number(value)
        return
    if type(value) is str:
        yield line_prefix + json.dumps(value, ensure_ascii=False)
        return
    if type(value) is list:
        if not value:
            yield line_prefix + "[]"
            return
        yield line_prefix + "[\n"
        for index, item in enumerate(value):
            yield from _canonical_text_chunks(item, level + 1)
            yield ",\n" if index < len(value) - 1 else "\n"
        yield indent + "]"
        return
    if type(value) is dict:
        if not value:
            yield line_prefix + "{}"
            return
        yield line_prefix + "{\n"
        keys = sorted(value)
        for index, key in enumerate(keys):
            key_prefix = json.dumps(key, ensure_ascii=False) + ": "
            yield from _canonical_text_chunks(value[key], level + 1, key_prefix)
            yield ",\n" if index < len(keys) - 1 else "\n"
        yield indent + "}"
        return
    raise ValueError(f"unsupported canonical JSON value {type(value).__name__}")


def iter_canonical_json_bytes(value: Any) -> Iterator[bytes]:
    """Yield sorted, finite canonical JSON without whole-document materialization."""

    maximum_chunk_bytes = 64 * 1024
    buffered = bytearray()
    for text in _canonical_text_chunks(value, 0):
        encoded = text.encode("utf-8")
        offset = 0
        while offset < len(encoded):
            available = maximum_chunk_bytes - len(buffered)
            consumed = min(available, len(encoded) - offset)
            buffered.extend(encoded[offset : offset + consumed])
            offset += consumed
            if len(buffered) == maximum_chunk_bytes:
                yield bytes(buffered)
                buffered.clear()
    buffered.extend(b"\n")
    if buffered:
        yield bytes(buffered)


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize sorted, finite JSON with two-space indentation and LF."""

    return b"".join(iter_canonical_json_bytes(value))


def canonical_json_sha256(value: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter_canonical_json_bytes(value):
        digest.update(chunk)
    return digest.hexdigest()
