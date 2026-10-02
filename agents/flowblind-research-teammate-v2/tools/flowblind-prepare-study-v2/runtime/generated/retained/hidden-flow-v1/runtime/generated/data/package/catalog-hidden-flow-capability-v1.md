# Catalog-native hidden-flow capability v1

## Status and scope

Capability version `1.1.0` and portable package version `1.0.0` define an
isolated reusable capability for a future FlowBlind Research Teammate v2
router. It prepares and runs one host-selected canonical hidden-flow problem
without changing the current shared catalog router or teammate package, guided
research v2, legacy `flowblindResearch` 1.1.3, frozen evidence, the Validation
Teammate, or any source-specific hidden-flow catalog.

The implementation is under
`tools/catalogCapabilities/hiddenFlow/`. Public JSON contracts use only the
`flowblind-catalog-hidden-flow-` schema prefix.

The committed portable image context is under
`tools/catalogCapabilities/hiddenFlow/package/`. Its generated runtime, policy,
declaration, dependency-complete reviewed source copies, Python solver,
schemas, and package lock are content-addressed and verified before either
action can be called. The build checks the bundler module graph against the
reviewed-source inventory so a new runtime-affecting repository module cannot
silently disappear from provenance.

The capability reuses the existing:

- `parseHiddenFlowProblem` structural and resource validation;
- `HIDDEN_FLOW_LIMITS`;
- compact-basis and solver-request compilation;
- the same bounded direct-Clarabel solver contract through the new
  `PinnedPythonProcessHiddenFlowSolverAdapter`;
- `verifyHiddenFlowSupportResult` independent numerical verification; and
- `renderHiddenFlowEvidenceReportMarkdown` neutral evidence report.

It does not invent a new hidden-flow method or scientific acceptance rule.
The generic draft-07 `hidden-flow-problem.schema.json` is a syntactic
prefilter shared with older code. Package acceptance is defined by the
2020-12
`flowblind-catalog-hidden-flow-problem-acceptance-v1.schema.json` projection,
the exact `parseHiddenFlowProblem` parser, canonical bytes, and executable
preflight. The authority attests only that bounded contract, allowed
observation and target types, pinned solver/runtime closure, and neutral
finite-basis claim boundary. It does not attest physical truth, source
accuracy, measurement validity, clinical use, or a model/user approval.

## Scientist-facing boundary

The scientist supplies only:

```json
{
  "goal": "Quantify the largest observation-compatible hidden flow at the declared target.",
  "details": "Optional ordinary-language interpretation context."
}
```

`details` may be omitted or `null`. No scientist-facing field accepts a hash,
path, protocol ID, tool name, run ID, attachment reference, or approval
boolean. The host provides bytes for one selected canonical hidden-flow problem
to preparation and bytes for one selected preparation bundle to execution.

Preparation is result-free. The run invocation itself is the host confirmation
boundary; the run contract intentionally has no `approved` property.

Schema:
[`flowblind-catalog-hidden-flow-input-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-input-v1.schema.json).

## Generic reviewed-problem authority

The authority is
`attested-generic-hidden-flow-problem-authority-v1`, governed by
`flowblind-catalog-hidden-flow-generic-review-policy-v1` version `1.0.0`.
Its scope is deliberately narrower than scientific truth review:

- generic draft-07 `HiddenFlowProblem` syntax as a prefilter only;
- the package-specific 2020-12 acceptance projection with the 96-basis,
  1,024-cell, and `1e100` magnitude limits;
- the existing `parseHiddenFlowProblem` parser;
- observations `point-component` and `point-direction`;
- targets `point-component`, `point-direction`, `point-speed-envelope`,
  `region-component`, and `point-strain-component`;
- the existing `HIDDEN_FLOW_LIMITS`;
- result-free compilation of the basis and every solver request;
- the hash-pinned Python/Clarabel runtime and independent verifier; and
- the neutral finite-basis claim boundary.

It explicitly records `not-attested` for physical truth, source accuracy,
measurement validity, and clinical use. It records
`not-accepted-as-authority` for model/user approval. It accepts only bytes from
the host-selected attachment channel; no problem ID, hash, path, threshold, or
approval field exists in public input.

The package authority is created only from the runtime authority returned by
the generated package verifier. The verifier checks an exact allowlist of
every runtime file and directory, rejects links, unsupported entries,
case-aliased paths, and unmanifested Python parents or shadow modules, and
places the runtime authority in a process-local `WeakSet`; structurally similar
caller objects are rejected. The generated verifier cannot attest its own
bytes. A host-allowlisted final image/verifier digest remains the root of
activation trust.

Schemas:
[`flowblind-catalog-hidden-flow-review-policy-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-review-policy-v1.schema.json),
[`flowblind-catalog-hidden-flow-review-attestation-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-review-attestation-v1.schema.json),
and
[`flowblind-catalog-hidden-flow-package-evidence-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-package-evidence-v1.schema.json).
The exact package acceptance projection is
[`flowblind-catalog-hidden-flow-problem-acceptance-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-problem-acceptance-v1.schema.json).

## Integration API

The supported integration surface is the verifier-gated packaged runtime and
the declarative future adapter contract in
`tools/catalogCapabilities/hiddenFlow/adapterContract.ts`. The lower-level
`createCatalogHiddenFlowCapability`, review-authority interface, and solver
adapter remain unattested internal/test composition seams and are not exported
from the stable root barrel.

The future shared-v2 route key is exactly:

```text
(methodId, methodVersion, action)
finite-basis-hidden-flow-v1 @ 1.1.0
family: finite-basis-observation-compatible-hidden-flow-v1
package: 1.0.0
```

The generic action names are not route keys by themselves. A shared adapter
may expose only the sealed package port; it must not accept raw
`reviewAuthority`, `solver`, executable path, Python module root, image label,
or approval injection. A preparation bundle must be routed back to the exact
method version and package closure that created it. Version or closure drift
fails typed package verification rather than falling forward silently.

Scientist input is exactly `{ goal, details? }`. The host selects immutable
problem and preparation snapshots. Run confirmation is host-owned,
non-serializable, and performed immediately before invocation; no `approved`
Boolean or persisted approval receipt belongs in this contract.

### Prepare

```ts
await adapter.prepare({
  methodId: 'finite-basis-hidden-flow-v1',
  methodVersion: '1.1.0',
  action: 'prepare-study',
  input: { goal, details },
  selectedProblemSnapshot,
  signal,
})
```

Input:

| Value | Supplied by | Contract |
| --- | --- | --- |
| `goal` | Scientist | Trimmed NFC ordinary-language text, 1-4,096 Unicode code points |
| `details` | Scientist | Optional trimmed NFC ordinary-language text, 1-4,096 Unicode code points |
| `selectedProblemSnapshot` | Catalog host | Exactly one immutable canonical stable-JSON accepted `HiddenFlowProblem` v1 document |

Success returns:

```ts
{
  response: {
    schemaVersion: 1
    capabilityVersion: '1.1.0'
    status: 'prepared-awaiting-confirmation'
    containsResults: false
    humanContext: { goal: string; details: string | null }
    problem: {
      id: string
      title: string
      targetType: HiddenFlowTarget['type']
      targetTitle: string
      observationRows: number
      retainedBasisFunctions: number
      solverRequestCount: number
    }
    review: {
      authorityVersion:
        'attested-generic-hidden-flow-problem-authority-v1'
      reviewScope:
        'generic-problem-contract-parser-and-executable-preflight-only'
      claimBoundary:
        'finite-basis-declared-model-only-no-physical-truth-source-validity-or-clinical-inference'
    }
    preparationBundle: CatalogHiddenFlowArtifactIdentity
  }
  bundle: CatalogHiddenFlowArtifact
}
```

`CatalogHiddenFlowArtifact` adds in-memory `bytes` to the serializable identity.
The host persists or transfers those exact bytes. Preparation failures return
`status: "refused"` and `bundle: null`.

Preparation performs no solve. It:

1. rejects empty, oversized, invalid UTF-8, or invalid JSON;
2. parses through `parseHiddenFlowProblem`;
3. requires the selected bytes to equal the stable-JSON serialization of the
   validated problem;
4. compiles the basis and every solver request as a result-free executable
   preflight;
5. obtains an attestation limited to the generic parser, supported types,
   resource limits, pinned runtime, and neutral claims;
6. records basis and request digests, counts, limits, method identity, review
   evidence, runtime requirements, and package identities; and
7. emits one content-addressed bundle.

Bundle schema:
[`flowblind-catalog-hidden-flow-preparation-bundle-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-preparation-bundle-v1.schema.json).

### Run

```ts
await adapter.run({
  methodId: 'finite-basis-hidden-flow-v1',
  methodVersion: '1.1.0',
  action: 'run-and-verify-study',
  input: { goal, details },
  preparationBundleSnapshot,
  confirmedInvocation,
  signal,
})
```

Input:

| Value | Supplied by | Contract |
| --- | --- | --- |
| `goal`, `details` | Host-preserved scientist context | Must exactly match the preparation bundle |
| `preparationBundleSnapshot` | Catalog host | The exact immutable canonical bundle bytes returned by prepare |
| `confirmedInvocation` | Catalog host | Opaque, non-serializable confirmation capability; never scientist/model data |
| `signal` | Integration/runtime | Optional cancellation signal |

The run path reconstructs the preparation bundle from its embedded problem and
context, compares the reconstructed bytes to the selected bytes, recompiles the
solver plan, and compares the preflight. It therefore has no dependency on a
prior process, local path, cache entry, database row, or mutable in-memory
association.

Execution then runs the same plan twice through the existing solver adapter and
independent verifier. The full stable-JSON `HiddenFlowSearchResult` from both
executions must be byte-identical. A mismatch returns typed `unavailable` and
publishes no artifacts.

On a deterministic verified execution, the API returns:

```ts
{
  response: {
    schemaVersion: 1
    capabilityVersion: '1.1.0'
    status: 'report-complete'
    containsResults: boolean
    humanContext: { goal: string; details: string | null }
    problem: {
      id: string
      title: string
      targetId: string
      targetType: HiddenFlowTarget['type']
    }
    review: {
      authorityVersion:
        'attested-generic-hidden-flow-problem-authority-v1'
      reviewScope:
        'generic-problem-contract-parser-and-executable-preflight-only'
      claimBoundary:
        'finite-basis-declared-model-only-no-physical-truth-source-validity-or-clinical-inference'
    }
    deterministicReplayMatched: true
    outcome: CatalogHiddenFlowOutcome
    artifacts: {
      json: CatalogHiddenFlowArtifactIdentity
      markdown: CatalogHiddenFlowArtifactIdentity
    }
    publication: {
      state: 'uncommitted-core-bytes'
      promotable: false
    }
  }
  artifacts: {
    json: CatalogHiddenFlowArtifact
    markdown: CatalogHiddenFlowArtifact
  }
}
```

The in-memory core returns uncommitted JSON and Markdown bytes only. The JSON
binds the preparation identity, human context, problem identity, both replay
digests, typed outcome, and the complete closed
`HiddenFlowEvidenceReport`. The Markdown includes an invariant authority
boundary and never calls a verifier-rejected value feasible.

The packaged mount adapter returns `publication.state: "marker-verified"` only
after installing and re-reading
`flowblind-hidden-flow-study-<preparation-sha256>/report-verification.json`.
Its success response replaces the member references with fixed set references,
adds `artifacts.verification`, and marks the set as host-promotion eligible.

Action-response schema:
[`flowblind-catalog-hidden-flow-action-response-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-action-response-v1.schema.json).
Verified-run schema:
[`flowblind-catalog-hidden-flow-verified-run-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-verified-run-v1.schema.json).
Evidence schema:
[`flowblind-catalog-hidden-flow-evidence-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-evidence-v1.schema.json).
Report-verification schema:
[`flowblind-catalog-hidden-flow-report-verification-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-report-verification-v1.schema.json).

These JSON Schemas are structural contracts. Package and router consumers must
also call the exported
`assertCatalogHiddenFlowActionResponseSemanticContract` validator (and its
report-set-specific
`assertCatalogHiddenFlowReportSetSemanticContract` helper). Semantic validation
requires `matched: true` to have equal first/replay hashes, binds the preparation
artifact digest to its content-addressed name and study directory, and requires
the JSON, Markdown, marker, action response, and publication directory to name
one canonical report set.

## Typed outcomes

The capability never converts a solver or verification failure into
infeasibility, zero, or a success-shaped numerical result.

| `kind` | Meaning | `containsResults` |
| --- | --- | --- |
| `numerical` | An accepted finite candidate, verified optimum, verified directional lower bound, full-observation zero-nullity result, or degenerate zero-response result | `true` |
| `infeasible` | The existing verifier accepted a `PrimalInfeasible` certificate within declared tolerances | `true` |
| `unavailable` inside `report-complete` | Independently accepted verified-unbounded evidence; no finite value exists, but the evidence set is report-bearing | `false` |
| top-level `unavailable` | Verification was not accepted, deterministic replay differed, the runtime failed, output exceeded its bound, or the operation was cancelled; no artifacts exist | `false` |

Numerical outcomes always state the original evidence state, value, unit,
qualification, and nullable rigorous upper bound. A directional speed result is
reported as a lower bound only. Infeasible outcomes have no `value`. Unavailable
outcomes have a reason and no scientific value.

## Content-addressed and restart-safe semantics

The canonicalization rule is stable JSON: object keys sorted recursively,
two-space indentation, finite JSON values only, UTF-8, and one trailing newline.

The bundle has two identities:

1. `association.sha256` hashes all immutable semantic bindings: human context,
   capability and method versions, complete canonical problem, executable
   preflight, limits, data-handling declaration, and runtime requirements.
2. The returned artifact SHA-256 hashes the complete serialized bundle bytes.
   Its generated reference is
   `flowblind-catalog-hidden-flow-preparation-<sha256>.json`.

The bundle embeds the complete canonical problem because the hidden-flow
problem is itself the bounded scientific input. A restarted worker needs only
the selected bundle bytes and the preserved ordinary-language context. It does
not recover a path, lookup token, process-local handle, or hidden approval
state.

Run artifacts are content-addressed inside one deterministic set directory.
The packaged publisher installs `verified-run.json` and `report.md`, then
installs `report-verification.json` last as the only point of no return. The
closed marker binds the preparation bundle, problem, package/software,
deterministic replay, and exact member identities. An identical retry verifies
and returns the same committed set. Divergent members, a partial committed set,
and tampered bytes are distinct typed failures.

Each atomic install uses an invocation-owned UUID staging name. Cleanup is
authoritative: a retry reconciles only a correctly named staging entry whose
bytes or hard-link inode match the expected final member, requires the unlink
to succeed, synchronizes the directory, and only then applies the unchanged
single-link ordinary-file integrity check to committed artifacts.

Cancellation before marker installation returns cancellation with no committed
set; matching member files may remain explicitly uncommitted and are reconciled
on retry. Once marker installation begins, the package finishes read-back and
returns committed success even if cancellation arrives. The marker does not
claim distributed exactly-once promotion. The host owns mount isolation,
retention, and promotion, and must promote only a marker-verified set.

## Limits and failure closure

The preparation bundle records the exact existing `HIDDEN_FLOW_LIMITS`,
including:

- 16 MiB problem and individual solver-result limits;
- 96 basis functions;
- 256 observation rows and 24,576 observation-matrix entries;
- 64 directional or batch requests;
- 32 MiB aggregate solver input and 64 MiB aggregate solver output; and
- 70,000 canonical matrix entries.

The bundle is limited to 17 MiB, allowing bounded metadata around a problem
that is itself limited to 16 MiB. Verified JSON is limited to 128 MiB and the
neutral Markdown report to 16 MiB. An oversized deterministic result is typed
as unavailable and no partial artifact is returned.

Structural, canonicalization, executable-preflight, bundle, and context
failures return `status: "refused"` with no artifact. Runtime, cancellation,
rejected verification, or replay failures return `status: "unavailable"` with
no artifact. Only independently accepted evidence plus deterministic replay is
eligible for report construction. Publication additionally distinguishes
`concurrent-publication-conflict`, `output-publication-partial`, and
`output-artifact-tampered`.

## Docker and runtime dependencies

`npm run hidden:capability:build` produces the self-contained runtime at
`tools/catalogCapabilities/hiddenFlow/package/runtime/`. The generated package
lock attests the bundled Node runtime, three executable facades, all capability
schemas, the generic problem schema/parser, basis/operator/verifier/report
sources, capability sources, Python solver sources, hash-pinned requirements,
container definition, public contract, review policy, and declaration.

The image context fixes:

- platform `linux/amd64`;
- Node
  `node:22.22.0-bookworm-slim@sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94`;
- Python
  `python:3.12.14-slim@sha256:2fe5997d249a808b8eeea52c58a1dbffbba28754dc11699ef5c029f2d818ce79`;
- wheel hashes for `clarabel==0.11.1`, `cffi==2.1.1`, `numpy==2.2.6`,
  `pycparser==3.0`, and `scipy==1.15.3`;
- requirements-lock SHA-256
  `1ffda1962375e2d2d77b794b7a930d55902869a2923e695ad333a3f8e0d7a4ed`;
- the attested `tools.hidden_flow_solver` source subtree executed with isolated
  Python startup and an explicit trusted module root;
- all declared BLAS/OpenMP thread variables fixed to `1`.

The container runs as `10001:10001`. The reviewed execution profile requires a
read-only root filesystem, no network, `no-new-privileges`, dropped
capabilities, and a bounded `noexec,nosuid,nodev` `/tmp` tmpfs. The pinned
adapter uses a minimal environment, 60-second child-process timeout, bounded
request/result files, and `AbortSignal` cancellation that terminates the Python
child. Solver evidence must report Python `3.12.14`, Clarabel `0.11.1`, NumPy
`2.2.6`, SciPy `1.15.3`, the pinned Python image, `x86_64`, and single-threaded
direct QDLDL. Any mismatch is typed `runtime-identity-mismatch`.

The package exposes:

- `flowblind-hidden-flow-prepare.mjs`;
- `flowblind-hidden-flow-run.mjs`; and
- `flowblind-hidden-flow-declaration-preview.mjs`.

The first two check role labels as defense in depth; `FLOWBLIND_TOOL_ROLE` is
not immutable image authority. Both verify the exact runtime tree and package
lock before loading the bundled runtime. Attachment discovery streams with
`opendir`, applies the 64-entry limit and cancellation during traversal, and
then revalidates the selected single-link JSON file around a bounded read. Run
publication uses the marker-last transaction described above.

The declaration preview returns the exact two actions, `prepare` confirmation
`Disabled`, `run` confirmation `Enabled`, scientist-only input schema, review
scope, runtime confinement, and current package/lock identities. It is the
integration handoff for a future shared two-action method router; this branch
does not modify that router or the current teammate package.

Schemas:
[`flowblind-catalog-hidden-flow-declaration-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-declaration-v1.schema.json)
and
[`flowblind-catalog-hidden-flow-package-lock-v1.schema.json`](../schemas/flowblind-catalog-hidden-flow-package-lock-v1.schema.json).

## Focused tests

`tools/catalogCapabilities/hiddenFlow/hiddenFlowCapability.test.ts` executes:

- public-input exclusion of technical control fields;
- fail-closed behavior without a reviewed-problem authority;
- generic review-attestation binding with explicit non-truth claims;
- deterministic result-free preparation and schema validation;
- unchanged draft-07 and 2020-12 schema validation plus exact 96/97 basis,
  1,024/1,025 cell, and numeric-magnitude boundaries;
- noncanonical input, extra technical field, bundle tampering, and human-context
  drift refusal;
- a real numerical solve, independent verification, deterministic replay, and
  neutral report generation through the existing Python adapter;
- a real verified-infeasible solve with no numerical value;
- a real verified-unbounded solve typed as unavailable with no invented value;
- deterministic verifier rejection returning artifact-free `unavailable`;
- closed nested evidence and `containsResults`/outcome schema rejection cases;
- marker-last publication, identical retry, pre/post-marker cancellation,
  divergent output, partial committed set, and tamper handling;
- runtime failure classified as unavailable rather than infeasible; and
- mismatched pinned runtime evidence refused without a scientific result; and
- accepted solver evidence with deliberately drifting replay bytes refused as
  a deterministic replay mismatch.

The portable Node tests additionally cover branded direct invocation,
declaration preview, clean-process restart, attachment-root typing, streaming
entry caps, bundle tamper, tool-role mismatch, package-lock tamper, verifier
cancellation, and rejection of an unmanifested Python parent by both verifier
and repository validator before solver loading. The Docker smoke builds both
role-labelled images and proves the real pinned Python/Clarabel closure and
marker output under non-root, read-only, no-network execution.

```text
npm run hidden:capability:check
npm run hidden:capability:freshness:check
npm run hidden:capability:release:check
```

`hidden:capability:check` starts with a non-mutating clean rebuild comparison,
so stale, missing, or extra committed runtime output fails before a committed
build can empty or repair it. It then runs the focused TypeScript check, package
build, focused/portable tests, exact-tree/schema validation, and a final
non-mutating comparison. The named release gate adds Docker smoke without
putting Docker in broad default tests.

The remaining activation work is outside this isolated capability: register
the exact `(methodId, methodVersion, action)` tuple in shared v2; bind separate
prepare/run resources to host-allowlisted final image digests, exact
command/entrypoint and environment; enforce non-root, no-network,
read-only-root flags; create immutable snapshots and isolated output mounts;
perform real run confirmation; promote only marker-verified sets; and provide a
per-method kill switch and telemetry. No package response attests physical
truth, source accuracy, measurement validity, clinical relevance, or
user/model approval.
