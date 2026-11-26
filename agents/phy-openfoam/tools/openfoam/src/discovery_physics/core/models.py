"""Strict, physics-independent public records. No model output is executable code."""

from __future__ import annotations

import math
import re
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,95}$")]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Number = Annotated[float, Field(allow_inf_nan=False)]
Scalar = StrictBool | StrictInt | StrictFloat | str


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Verdict(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    INCONCLUSIVE = "INCONCLUSIVE"
    CORRECT_AND_RERUN = "CORRECT_AND_RERUN"


class Check(Record):
    id: Identifier
    metric: Identifier
    operator: Literal["lt", "le", "gt", "ge", "eq", "between", "true"]
    threshold: Scalar | list[Number] | None = None
    unit: str = Field(default="1", max_length=80)
    category: Literal[
        "mesh", "execution", "setup", "boundary", "admissibility", "conservation",
        "horizon", "stationarity", "reference", "discretization", "validation",
    ]
    rationale: str = Field(min_length=8, max_length=2000)
    failure: Literal["hard", "incomplete"] = "hard"

    @model_validator(mode="after")
    def valid_threshold(self) -> Check:
        if self.operator == "true":
            if self.threshold is not None:
                raise ValueError("a true check has no threshold")
        elif self.operator == "between":
            if not isinstance(self.threshold, list) or len(self.threshold) != 2:
                raise ValueError("between requires two finite, ordered bounds")
            if not self.threshold[0] < self.threshold[1]:
                raise ValueError("between bounds must be increasing")
        elif self.operator != "eq":
            if type(self.threshold) not in (int, float) or not math.isfinite(self.threshold):
                raise ValueError("numeric comparison requires a finite numeric threshold")
        elif self.threshold is None or isinstance(self.threshold, list):
            raise ValueError("eq requires a scalar threshold")
        return self


class Objective(Record):
    id: Identifier
    description: str = Field(min_length=5, max_length=2000)
    claim: Literal[
        "numerical_health", "conservation", "stationarity", "reference_agreement",
        "mesh_independence", "physical_validation", "quantity", "custom",
    ] = "quantity"
    check_ids: list[Identifier] = Field(default_factory=list, max_length=128)


class Assumption(Record):
    parameter: str = Field(min_length=1, max_length=128)
    value: Scalar
    unit: str = Field(default="1", max_length=80)
    source: Literal["user", "derived", "documented_default", "needs_confirmation"]
    justification: str = Field(min_length=5, max_length=2000)


class Contract(Record):
    schema_version: Literal["1.0"] = "1.0"
    id: Identifier
    title: str = Field(min_length=5, max_length=256)
    requested_prompt: str = Field(min_length=5, max_length=32000)
    regime: Literal["steady", "transient", "statistical"]
    objectives: list[Objective] = Field(min_length=1, max_length=128)
    checks: list[Check] = Field(min_length=1, max_length=256)
    assumptions: list[Assumption] = Field(default_factory=list, max_length=128)
    limitations: list[str] = Field(default_factory=list, max_length=64)
    # "proposed" cannot accept; preparation freezes it before any solver runs.
    authority: Literal["proposed", "frozen", "user_approved", "reviewed_benchmark"] = "proposed"
    reference: str = Field(default="No external validation claimed.", max_length=4000)

    @model_validator(mode="after")
    def unique_ids(self) -> Contract:
        for records in (self.checks, self.objectives):
            ids = [r.id for r in records]
            if len(ids) != len(set(ids)):
                raise ValueError("check and objective identifiers must be unique within their sets")
        return self


class Metric(Record):
    value: Scalar | None
    unit: str = Field(default="1", max_length=80)
    source: str = Field(min_length=1, max_length=1024)
    status: Literal["measured", "missing", "invalid"] = "measured"


class Evidence(Record):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    origin: Literal["native", "reconstructed", "synthetic"]
    solver_invoked: StrictBool
    contract_sha256: str
    case_sha256: str
    metrics: dict[str, Metric]
    artifacts: dict[str, str] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    runtime: dict[str, Any] = Field(default_factory=dict)


class CheckResult(Record):
    id: str
    state: Literal["PASS", "FAIL", "UNKNOWN"]
    metric: str
    value: Scalar | None = None
    unit: str = "1"
    threshold: Scalar | list[Number] | None = None
    reason: str
    category: str
    failure: str


class Assessment(Record):
    run_id: str
    verdict: Annotated[Verdict, Field(strict=False)]
    evidence_origin: str
    solver_invoked: bool
    live_acceptance: bool
    contract_sha256: str
    checks: list[CheckResult]
    unresolved: list[str]
    limitations: list[str]


class Budget(Record):
    max_attempts: int = Field(default=4, ge=1, le=8)
    wall_seconds: int = Field(default=1800, ge=1, le=14400)
    cpus: int = Field(default=2, ge=1, le=64)
    memory_mb: int = Field(default=4096, ge=512, le=262144)
    max_cells: int = Field(default=200000, ge=1, le=5000000)
    max_output_mb: int = Field(default=2048, ge=1, le=32768)
    # Physical end time a correction may extend to; None means the diagnostic target.
    max_end_time: Positive | None = None
    # MPI ranks for the solve (domain decomposition); 1 means serial.
    mpi_ranks: int = Field(default=1, ge=1, le=64)

    @model_validator(mode="after")
    def ranks_fit(self) -> Budget:
        if self.mpi_ranks > self.cpus:
            raise ValueError("mpi_ranks cannot exceed cpus")
        return self


COMMAND_FLAGS = {"-overwrite", "-force", "-latestTime", "-noFunctionObjects", "-allGeometry",
                 "-allTopology", "-constant"}


class Command(Record):
    executable: Literal[
        "blockMesh", "checkMesh", "snappyHexMesh", "surfaceFeatures", "setFields",
        "renumberMesh", "decomposePar", "reconstructPar", "foamToVTK",
    ]
    args: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def allowed_args(self) -> Command:
        it = iter(self.args)
        for a in it:
            if a == "-dict":
                path = next(it, "")
                if not re.fullmatch(r"system/[A-Za-z0-9_.]+", path):
                    raise ValueError("-dict must name a file under system/")
            elif a not in COMMAND_FLAGS:
                raise ValueError(f"argument {a!r} is not allowed (allowed: {sorted(COMMAND_FLAGS)}, -dict)")
        return self


class Confirmation(Record):
    """A user's confirmation of an assumption the contract marked needs_confirmation."""

    parameter: str = Field(min_length=1, max_length=128)
    decision: Literal["confirmed"]
    confirmed_by: str = Field(min_length=2, max_length=200)
    note: str = Field(default="", max_length=2000)


class Gas(Record):
    gas_constant: Positive
    gamma: float = Field(gt=1, le=2, allow_inf_nan=False)


class FieldSpec(Record):
    name: Identifier
    unit: str = "1"
    positive: bool = False
    components: Literal[1, 3] = 1


class Compression(Record):
    axis: Literal[0, 1, 2] = 0
    transverse_axis: Literal[0, 1, 2] = 1
    transverse_max: Positive
    x_min: Number = 0.0
    x_max: Positive


class NozzleReference(Record):
    throat_radius: Positive
    exit_radius: Positive
    throat_x_min: Number
    throat_x_max: Positive
    total_pressure: Positive
    total_temperature: Positive
    wedge_degrees: float = Field(gt=0, le=10, allow_inf_nan=False)


class Quantity(Record):
    """A requested output read from a whitelisted function object."""

    name: Identifier
    function: Literal[
        "forces", "forceCoeffs", "probes", "surfaceFieldValue", "volFieldValue", "yPlus",
    ]
    settings: dict[str, str] = Field(default_factory=dict, max_length=32)
    column: str = Field(min_length=1, max_length=128)
    statistic: Literal["last", "window_mean", "window_relative_span"] = "last"
    unit: str = Field(default="1", max_length=80)


class Derived(Record):
    """A deterministic combination of measured metrics (no model arithmetic in verdicts)."""

    name: Identifier
    op: Literal["difference", "ratio", "scale", "abs_rel_error_pct"]
    a: str = Field(min_length=1, max_length=128)
    b: str | None = Field(default=None, max_length=128)
    factor: Number = 1.0
    factor_unit: str = Field(default="1", min_length=1, max_length=80)
    reference: Number | None = None
    reference_unit: str | None = Field(default=None, min_length=1, max_length=80)
    unit: str = Field(default="1", max_length=80)


class Diagnostics(Record):
    fields: list[FieldSpec] = Field(min_length=1, max_length=32)
    derived: list[Derived] = Field(default_factory=list, max_length=32)
    initial_values: dict[str, Number | list[Number]] = Field(default_factory=dict)
    reference_hashes: dict[str, str] = Field(default_factory=dict)
    quantities: list[Quantity] = Field(default_factory=list, max_length=32)
    patches: list[Identifier] = Field(default_factory=list, max_length=64)
    inlet: Identifier | None = None
    outlet: Identifier | None = None
    impermeable_patches: list[Identifier] = Field(default_factory=list, max_length=64)
    expected_cells: int | None = Field(default=None, ge=1)
    dimensions: Literal[2, 3] | None = None
    gas: Gas | None = None
    target_time: Positive
    mass_balance: bool = False
    stationarity_window: Positive | None = None
    compression: Compression | None = None
    nozzle: NozzleReference | None = None
    normalized: bool = False

    @model_validator(mode="after")
    def consistency(self) -> Diagnostics:
        names = [f.name for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("field names must be unique")
        if len(set(self.patches)) != len(self.patches):
            raise ValueError("patch names must be unique")
        if not set(self.impermeable_patches).issubset(self.patches):
            raise ValueError("impermeable patches must be included in measured patches")
        if self.mass_balance and (not self.inlet or not self.outlet):
            raise ValueError("mass balance requires explicit inlet and outlet")
        if self.mass_balance and "rho" not in names:
            raise ValueError("compressible mass balance requires native rho measurement")
        if any(p and p not in self.patches for p in (self.inlet, self.outlet)):
            raise ValueError("inlet and outlet must be measured patches")
        if self.nozzle and self.gas is None:
            raise ValueError("nozzle reference requires declared gas properties")
        return self


class CaseBundle(Record):
    """Free-form case files, not a closed scenario list. The solver is capability-bound."""

    schema_version: Literal["1.0"] = "1.0"
    name: Identifier
    adapter: Literal["openfoam-foundation14"] = "openfoam-foundation14"
    solver: Identifier
    files: dict[str, str] = Field(min_length=3, max_length=512)
    mesh: list[Command] = Field(default_factory=lambda: [Command(executable="blockMesh")])
    diagnostics: Diagnostics
    contract: Contract
    budget: Budget = Field(default_factory=Budget)

    @model_validator(mode="after")
    def basic_files(self) -> CaseBundle:
        required = {"system/controlDict", "system/fvSchemes", "system/fvSolution"}
        if not required.issubset(self.files):
            raise ValueError("case requires controlDict, fvSchemes, and fvSolution")
        if not self.mesh:
            raise ValueError("at least one meshing command is required")
        return self