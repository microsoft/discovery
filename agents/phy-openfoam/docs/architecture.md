# Architecture

`phy-openfoam` separates open-ended case authoring from deterministic scientific
authority. The [landing page](../README.md) describes the user interface;
[deployment](deployment.md) describes the additional unqualified cloud boundary.

## Components and identities

| Component | Responsibility | Source |
|---|---|---|
| Reasoning agent | Clarify, author a bundle, diagnose, propose one action | [Skill](../skills/phy-openfoam/SKILL.md), optional [companion](../integrations/phy-openfoam.agent.md) |
| Host CLI | JSON interface; no model calls or physics MCP server | [CLI](../tools/openfoam/src/discovery_physics/cli.py) |
| Portable core | Typed contracts, check evaluation, policy, reports, integrity | [Models](../tools/openfoam/src/discovery_physics/core/models.py), [checks](../tools/openfoam/src/discovery_physics/core/checks.py), [policy](../tools/openfoam/src/discovery_physics/core/policy.py) |
| OpenFOAM adapter | Safety checks, freezing, execution, native extraction | [Runner](../tools/openfoam/src/discovery_physics/openfoam/runner.py), [safety](../tools/openfoam/src/discovery_physics/openfoam/safety.py), [extractor](../tools/openfoam/src/discovery_physics/openfoam/extract.py) |
| Worker image | Foundation 14 meshing, solver, monitors, geometry dependencies | [Dockerfile](../tools/openfoam/Dockerfile), [worker](../tools/openfoam/src/discovery_physics/worker.py) |
| Optional service | In-image `evaluate`, `study`, and `lint` actions | [Service](../tools/openfoam/src/discovery_physics/service.py), [action manifest](../tools/openfoam/tool.yaml) |

The agent and skill name is `phy-openfoam`. The independently installable Python
distribution remains `discovery-physics-openfoam`, import module
`discovery_physics`, command `discovery-physics`. All components needed for this
entry are below this directory; no generated catalog projection or parent-project
README is required. Discovery/CLIO, the container engine, and their authentication
are independently installed external dependencies.

## Lifecycle and scientific authority

1. **Scope.** State objectives, units, assumptions, reference sources, and
   thresholds before seeing results. There is no scenario-table router or
   universal physics guarantee: unsupported modules and unmeasurable objectives
   are blockers, not permission to substitute a convenient benchmark.
2. **Lint and freeze.** `lint` checks binding, coverage, safety, and cost.
   `prepare` freezes the case, scientific contract, execution plan, and budget.
   Mandatory baseline checks cannot be removed by the reasoning agent.
3. **Confirm.** Assumptions with `source: needs_confirmation` block `execute`.
   A method or fidelity substitution uses `method_substitution`. Only after the
   user decides may `confirm` record that decision. `confirmed_by` is an audit
   field, **not authenticated human identity**.
4. **Execute and measure.** The worker generates native evidence. Published
   reference results, synthetic fixtures, and model prose cannot stand in for
   new solver output or create a live-execution receipt.
5. **Assess and gate.** Code evaluates every required check. The model proposes
   one action; policy permits it only within the frozen contract and budgets.
   Corrections keep the contract hash. A different contract requires a disclosed
   new lineage, not a silent threshold change.
6. **Finalize.** Reports are rendered from recorded metrics and deterministic
   decisions. Live acceptance requires `final_verdict: ACCEPT` and
   `live_acceptance: true`; interpretation added by the model is non-authoritative.

Verdicts are `ACCEPT`, `REJECT`, `INCONCLUSIVE`, and `CORRECT_AND_RERUN`.
Missing, non-finite, wrong-type, wrong-unit, or insufficient evidence never passes
vacuously. Objectives without adequate check coverage cannot be accepted. Hard
physical/numerical failures outrank healthy but incomplete development or horizon
checks. A successful process exit does not establish scientific acceptance.

### Audited initialization

The authored initial fields and setup dictionaries stay in the original frozen
input hash; `setFields` does **not** exempt `0/` from integrity checks. The worker
first checks its copied input, then records per-file before/after hashes for each
setup command. Only a successful, explicitly frozen `setFields` command may
rewrite existing top-level initial fields. Changes to dictionaries, includes,
deleted fields or initial fields written by other setup commands fail the case
integrity check and prevent the solve. Generated mesh and derived geometry fields
retain their existing exclusions.

The raw worker packet records `runtime.setup_audit`: input/expected hashes,
command changes, and post-setup/final hashes. Initial fields and dictionaries
must remain unchanged after setup, including through solve/postprocessing.
Reference-file hashes remain independent constraints; a deliberately rewritten
field does not silently bypass its explicit reference hash. Continuations keep
the original problem hash, verify the parent's journal-pinned output case, and
bind the verified post-setup hash separately in the child plan. Initialization is
not rerun. None of this rewrites historical inputs, evidence or journals.

Acceptance means **satisfaction of the stated contract**, not universal physical
validity. Threshold quality, turbulence-model applicability, experimental
validation, and discretization uncertainty remain scientific review duties.
Normalized quantities must retain their recorded units; field names alone do
not justify assigning SI units.

## Transient and restart accounting

For transient mass accounting, stored mass and outward boundary flux give

$$
r_n = \frac{M_n-M_{n-1}}{\Delta t_n} + \Phi_n.
$$

Normalize using a nonzero declared flux scale. Unequal inlet and outlet fluxes
alone are not a transient conservation failure. Time series must be ordered,
finite, complete, and sufficiently populated. Difference within restart
segments, **and** audit that each restart continues the preceding checkpoint.
Discarding seam pairs without continuity evidence is not a valid correction.
Monitor precision and checkpoint consistency are part of the evidence path;
never repair a frozen run by hand-editing fields or logs.

## Execution and operator boundary

The host launches `blockMesh`, `checkMesh`, and `foamRun` through allowlisted
argument vectors, not model-supplied shell commands. The worker uses a non-root
identity, no network, a read-only root filesystem and input mount, dropped Linux
capabilities, and `no-new-privileges`. Output is confined to the designated mount
and temporary workspace; no host container socket or user credentials should be
mounted into the worker.

Safety checks reject unsafe paths, uploaded executable code, dynamic-code
dictionaries, coded functions or boundaries, external includes, host environment
expansion, untrusted libraries, and precomputed mesh substitution. The agent's
**host shell is not itself isolated by the worker container**. This is a hardened
local scientific runner, not a certified hostile multi-tenant service; use a
dedicated VM and separate privileges for hostile workloads.

CPU, memory, and PID enforcement fails closed by default. Only an operator may
authorize a disclosed unenforced-limit exception. An agent must not change
runtime settings, install privileged services, alter concurrency, or enable that
exception. The semaphore defaults to two concurrent solves; it is a queue policy,
not proof that OS resource controllers work. See [configuration](configuration.md).

## Integrity and retention boundary

The [integrity layer](../tools/openfoam/src/discovery_physics/core/integrity.py)
maintains a sequenced, hash-chained, HMAC-SHA-256-authenticated event journal with
a key outside the run directory. Verification and subsequent decisions check
journal-pinned artifacts and recompute assessments from pinned worker evidence.
Editable convenience assessments, reports, and state hints are not authority.

The raw worker packet stays at `output/evidence.json` inside its run directory,
with its byte digest pinned in the journal and its worker content digest in
`output/evidence.sha256`. The host-enriched `evidence.json` is a **different file
at the run root**. Assessment and permitted reassessment do not overwrite or
reformat the raw packet. Verification re-reads the raw worker file and recomputes
the enriched evidence and assessment; editing the convenience copy cannot
change the verified result.

These are **conditional local tamper-evidence properties**, not a public digital
signature. The same OS identity may read the HMAC key. A valid retained prefix
does not prove that no suffix was removed. Production needs separate key custody,
authenticated authorization, externally retained chain heads, and append-only
audit storage; these are not supplied by local packaging.

`cancel` preserves records; `recover` detects a missing executor. Lost or cancelled
execution cannot be promoted to live acceptance. `reassess` cannot rewrite a run
that already has a ruling or final decision. Preserve historical originals
immutably and keep private keys and native session metadata private. A sanitized
derivative is a **new artifact** with source hashes and transformation provenance,
not a repaired original journal.

The [retention interface](../tools/openfoam/src/discovery_physics/openfoam/retention.py)
can export a run, optionally including fields, and can compact old finalized
solver data after an operator review. Export does not automatically include all
ancestor/member runs, code, omitted fields, or external retention records. It is
not automatically complete or externally verifiable lineage. Never compact the
immutable historical originals retained for the retrospective record.

## Studies, design, MPI, and geometry

The [study layer](../tools/openfoam/src/discovery_physics/openfoam/study.py)
freezes member bundles and cross-run criteria before results exist. Each member
uses the ordinary gate. Criteria include accepted-member counts, three-grid GCI,
monotonicity, ranges, and best-candidate selection with an uncertainty margin.
Relevant cross-run claims require live accepted member lineages; one accepted
run cannot establish mesh independence.

Before staging any member, each numeric cross-run criterion must name a metric
declared by every member with the same nonblank unit label. The unit is bound by
the member diagnostics already frozen in the study; range bounds use that unit.
Assessment checks recorded evidence units again before GCI, monotonicity, range
or candidate ranking, and only unit-checked values can feed the advisory
surrogate. Missing, invalid or incompatible evidence yields `UNKNOWN`, never a
comparison of incompatible numbers or a default pass. There is no implicit unit
conversion: Pa and kPa must be explicitly converted to a common declared output
before preparation. Dimensionless/normalized outputs retain their recorded
label; matching labels alone do not prove a common physical normalization.

GCI criteria are evaluated before dependent `best` rankings regardless of their
position in the authored list. Each GCI is evaluated once; the signed study and
result/report order retain the original criterion order. A ranking may use a
referenced GCI only if it passes with finite nonnegative uncertainty; failed or
unavailable dependencies yield `UNKNOWN`, never an assumed zero margin.

Candidate separation must exceed the registered combined uncertainty for a
design-superiority claim. Seeded Latin-hypercube sampling is reproducible;
an advisory surrogate cannot accept an unexecuted optimum. MPI ranks are frozen
within the CPU budget, with decomposition and reconstruction handled by the
worker. Geometry conversion supports STEP, IGES, BREP, and STL to ASCII STL;
conversion does not guarantee arbitrary-CAD meshing or mesh quality.

## Service and validation boundaries

The service executes the worker as an in-container subprocess, without nested
Podman/Docker. Encoded JSON action inputs are not arbitrary shell fragments.
Local in-image execution does not demonstrate Discovery/Azure action dispatch.
The service's `platform-enforced` label identifies a code path, not a measurement
of cloud enforcement or isolation.

Keep unit/fixture tests, new CFD solves, CLIO behavioral scoring, raw model
judgments, and deployed platform requests separate. Historical scope and known
counterexamples are summarized in
[VALIDATION-HISTORY.md](../benchmarks/VALIDATION-HISTORY.md); no new 0.2.1 live
validation is implied by the relocation or documentation update.