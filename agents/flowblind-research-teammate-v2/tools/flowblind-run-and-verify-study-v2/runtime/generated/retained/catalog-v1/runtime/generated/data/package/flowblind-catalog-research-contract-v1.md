# FlowBlind catalog research contract v1

## Scope

This contract defines the reusable, catalog-native **FlowBlind Research
Teammate**. It supports exactly two reviewed capabilities:

- `regional-agreement-v1`: a paired reference/candidate, single-frame,
  planar, complete Cartesian grid; a deterministic 3 x 3 regional
  agreement/concordance study; and the reviewed Pearson correlation,
  range-normalized RMSE, mean absolute error, hotspot recall, and hotspot
  Jaccard endpoints.
- `vector-time-readiness-audit-v1`: one structured planar vector field or
  vector time series in the exact reviewed CSV forms; descriptive speed,
  structured derivative, frame-summary, complete-cycle, and typed
  wall-shear/temporal availability evidence.

The package is not a fixed VISC viewer, a source registry, an arbitrary-code
tool, an arbitrary method selector, or a generic scientific-verdict agent.
Hidden-flow optimization, external-validation studies, sensor-placement
planning, Home Flow QC, VISC'11, WeatherBench2, and synthetic data remain
separate methods or validation fixtures unless a separately reviewed
versioned catalog contract explicitly adds them.

The public package version is `1.0.0`. Its exact actions are:

1. `prepare-study`
2. `run-and-verify-study`

`prepare-study` accepts `researchGoal`, optional `decisionQuestion`, optional
`nextEvidenceIntent`, and common scientist-level declarations for `quantity`,
`coordinateUnit`, `valueUnit`, `provenance`, and `license`. Regional agreement
also requires `referenceMeaning` and `candidateMeaning`. Vector/time readiness
instead requires `vectorMeaning`, `vectorSourceKind`, `timeUnit`, and
`samplingKind`, with optional selected-time, frame-exposure, and complete-cycle
fields. `run-and-verify-study` accepts only the three human-context fields. The
runtime rejects additional properties and mixed-family detail sets. Dataset
and preparation-asset association is provided only through host-mounted
resources; no path, hash, sidecar, receipt, manifest, protocol, run, action, or
approval value is accepted from the scientist.

Capability routing is deterministic and fail-closed. Positive matching uses
the research goal and requires exactly one reviewed family; safety and
unsupported-method checks inspect all three human-context fields. Dataset
shape confirms compatibility but never selects a method by itself. If both or
neither family matches, the action returns `ambiguous`, `unsupported`, or
`needs-scientific-method` without reading scientific results. Every such
response includes ordinary-language guidance; ambiguity is resolved by
restating the scientific goal, never by entering a capability ID.
Capability-independent incompatibilities such as 3-D or sparse topology,
incompatible quantities, invented metrics or thresholds, and scientific
verdict requests take precedence over ambiguity. Vector/time matching is
limited to the implemented selected-frame speed/spatial-derivative audit and
speed-only frame/cycle summaries; temporal derivatives or temporal aggregation
of divergence, vorticity, strain, or wall shear require another reviewed
method.

The current `microsoft/discovery` schema at
`82db92769ac5e7c66f7028b0e2cd0260b67c63ef` does not permit the JSON Schema
keyword `additionalProperties` at the `tool.yaml` action-input root. The
portable package therefore carries and attests the complete public input
schema, including `additionalProperties: false` and the mutually exclusive
family branches, while the catalog YAML uses only the root keywords the pinned
schema permits: `type`, `properties`, and `required`. The YAML action
description explicitly states the additional branch-specific required fields,
and the agent collects only the matched branch. Runtime validation remains
authoritative and reports `capability-metadata-mismatch` when supplied details
belong to another family.

Managed actions transport scientist-authored strings through
Discovery-templated environment values. The shell command is static and
contains no user-controlled interpolation. The launchers decode the standard
Handlebars escaped form and apply the same display-text validation before the
values can influence identities or reports.

## Catalog and confirmation boundary

The agent configuration has human-in-the-loop enabled and data-handling tools
available. Preparation and execution are separate catalog tool resources:

- `prepare-study` has catalog confirmation disabled.
- `run-and-verify-study` has catalog confirmation enabled.

The run confirmation is a real host UI action immediately before tool
execution. It is not represented by an input field, model-authored sentence,
boolean, persisted approval, or preparation-bundle value. Cancelling the host
confirmation means the run process is not invoked and no success-shaped
structured content is required. A later retry recomputes every attachment
identity and presents confirmation again.

The package attestation binds the agent/tool confirmation policy. A package
whose run tool is not configured for confirmation fails closed. A host that
cannot enforce the declared confirmation policy is unsupported.

The in-package verifier is a consistency and drift control inside a trusted
image, not an external image-signature root. Deployment must additionally pin
and read back the built image digest, immutable command-to-tool binding, two
distinct tool resource IDs, their confirmation settings, and a non-writable
runtime root. The run facade also refuses the preparation image's attested
tool role.

The currently tested GitHub Copilot/Discovery App Preview `0.15.14` can
discover this custom-agent file and load both MCP sources, but cannot activate
the agent in chat. The official two-resource deployment/read-back path and
success-only promotion/remount semantics are likewise unproven. These are
external publication blockers, not conditions that local package attestation
can satisfy.

## Attachment contract

`prepare-study` receives exactly one host-mounted file:

- regional agreement: one candidate CSV with exact header
  `x,y,reference_value,candidate_value`; or
- vector/time readiness: one candidate CSV with exact header `x,y,u,v`,
  `x,y,u,v,valid`, `time,x,y,u,v`, or
  `time,x,y,u,v,valid`.

`run-and-verify-study` receives exactly three host-mounted files:

- the original candidate CSV; and
- one promoted preparation asset containing the generated
  `trusted-sidecar.json` and exact `preparation.json` bundle returned by
  `prepare-study`.

The runtime:

- confines every reference beneath the fixed attachment mount;
- rejects absolute paths, traversal, links, junctions/reparse indirection,
  non-regular files, uncertain hydration, and changed entries at and beneath
  the trusted host mount root;
- opens files read-only with no-follow semantics where the platform exposes
  them;
- checks allocation/hydration, byte limits, byte length, and SHA-256 before
  trusting content;
- revalidates stable file and ancestor identity after every read; and
- re-reads and re-hashes the source, generated sidecar, and preparation bundle
  immediately before execution.

No researcher source byte is copied into the package, preparation bundle, or
durable runtime state.

The host must provide an immutable read-only attachment snapshot for the
duration of each action and an invocation-owned output mount that cannot be
renamed or replaced by an untrusted concurrent writer. Runtime path and handle
checks are defense in depth, not a substitute for that mount-isolation
contract. Multi-link attachment files are rejected.

## Preparation

Preparation is result-free. It validates:

- the exact one-file attachment set;
- bounded, trimmed scientist-level quantity, meaning, unit, provenance, and
  licence declarations;
- a generated strict UTF-8, duplicate-key-free sidecar v2 with exact candidate
  basename/length/hash binding;
- required quantity, source meaning, reference/candidate meaning, coordinate
  unit, value unit, provenance, and licence declarations;
- two coordinate dimensions, one declared frame, paired values, exact four
  column CSV header, finite values, complete Cartesian topology, unique
  coordinates, and uniform axes;
- all nine 3 x 3 windows meeting the reviewed minimum of 30 paired points; and
- aggregate byte, row, field, grid-point, window, evaluation, and report
  budgets before the relevant allocation or computation.

For vector/time readiness it instead validates the exact vector CSV header,
finite values, optional `0`/`1` validity mask, one complete rectilinear x/y
grid per frame, identical coordinates across frames, unique and increasing
timestamps, no more than 64 significant decimal digits per coordinate,
aggregate point/frame/value budgets, declared units, source kind,
temporal sampling, optional exposure metadata, and optional closed cycle. It
freezes the reviewed readiness gates without calculating speed, derivative, or
temporal metrics.

The temporal projection is explicitly `single-frame` with exposure
`unspecified`; no instantaneous or frame-averaged exposure is inferred. The
geometry projection is an index-grid, non-equal-area view unless a later
separately versioned contract introduces reviewed physical-area semantics.

The successful status is `prepared-awaiting-confirmation` and
`containsResults` is `false`. The canonical preparation bundle binds:

- exact human context;
- source and sidecar identities and candidate binding;
- declarations, canonical CSV structure, geometry, temporal projection, and
  support counts;
- reviewed capability, method, preset, partition, endpoints, sufficiency
  rule, resource limits, canonical protocol, and freeze receipt;
- package, runtime, schema, report-renderer, and catalog-policy identities; and
- an association digest over all of those bindings.

The generated sidecar and bundle are published together in one deterministic
directory keyed by the preparation-bundle SHA-256. The sidecar carries only
the declarations and candidate identity; the bundle contains no source bytes,
endpoint values, baseline values,
regional values, verdicts, automatically collected PID, host path, saved
dataset ID, hostname, username, current time, random value, nonce run
directory, or bundled VISC artifact. Scientist-supplied human context,
meanings, units, provenance, licence, and the selected candidate basename are
retained verbatim in the preparation asset and may themselves contain
sensitive identifiers; the user must review the returned declaration preview
before requesting a run. The output directory is promoted as one result-free
catalog asset so the original CSV plus a selected canonical preparation asset
can be used in a clean chat; this promotion does not retain or register the
researcher source.

Preparation success includes a `declarationPreview` with two deliberately
separate projections:

- `unverifiedScientistAssertions` echoes the exact normalized quantity,
  meanings, units, provenance, and licence supplied for the study; and
- `validatedV1Projection` reports the runtime-established paired, planar,
  two-dimensional, single-frame CSV structure.

The teammate must show this preview and stop. A correction requires a new
preparation. The later run confirmation remains a real host action and is not
replaced by a stored approval field.

The runtime verifies the currently selected preparation directory's exact
filenames, common parent, content-addressed parent name, canonical bytes, and
internal bindings. Proving that this directory is the same host asset returned
in an earlier chat additionally requires an immutable host-owned asset
identity, which the pinned host has not demonstrated. V1 therefore does not
claim cross-action catalog-object continuity beyond the exact bytes currently
mounted.

Mount-relative parent directories are transport details, not scientific
authority. Candidate and preparation identities persisted in bundles and
reports use their bound portable basenames/internal names so byte-identical
reattachment under a different harmless host prefix produces byte-identical
verified outputs.

## Execution and verification

`run-and-verify-study` validates the complete bundle schema and canonical
bytes, verifies its package/software chain, verifies exact human context, then
re-reads and re-hashes every selected file. It strictly revalidates the
generated sidecar, reconstructs the preparation bundle from the original CSV
and bound declarations, and requires byte identity. Any drift refuses before
science.

Preparation portability in v1 is exact-build-only. A bundle is reusable after
a chat, process, or session restart only while both deployed tools use the
same attested package lock that created it. A package update requires either
re-preparation with the new matched tool pair or retention of the exact old
pair. Rolling mixed-build prepare/run operation is unsupported and returns
`preparation-build-mismatch`; package version text alone is not a
compatibility key.

After host confirmation, the runtime executes only the frozen reviewed
operation selected during preparation. Regional agreement runs the fixed 3 x
3 study. Vector/time readiness runs the existing validated audit for
instantaneous speed, structured derivatives, frame summaries, complete-cycle
coverage, and typed wall-shear/temporal availability. It performs an
independent deterministic replay and requires:

- byte-identical projected scientific result;
- exact source identity;
- exact protocol and preparation identity; and
- exact package/software identity.

Numerical or evaluation exceptions are typed `run-failed`; replay or binding
failures are typed `verification-failed`. Neither is represented as
infeasible, insufficient, or success-shaped output. Reviewed metric-level
`insufficient-evidence` and `unavailable` values remain typed values in an
otherwise verified result.

The successful status is `report-complete` and `containsResults` is `true`.
The response has top-level `humanContext`, `verifiedStudy`, and
`preparationEvidence`. `verifiedStudy` contains the verified neutral scientific
projection and exact identities for JSON, Markdown, self-contained HTML, and
the report-verification commit marker.

## Deterministic publication and recovery

The output directory is derived from the preparation-bundle SHA-256. It
contains no time, random value, PID, or host identity. Files are published
with exclusive create-or-verify semantics. The complete preparation
evidence, JSON, Markdown, and HTML are written before the
report-verification commit marker; the marker is the publication point of no
return. Files without a matching marker are explicitly unpublished and are
reconciled or refused on restart.

Vector CSV preparation validates bounded 64 Ki-character chunks, yields to the
runtime between chunks, and checks cancellation before decoding, after every
chunk, and before/after final canonicalization. Regional and shared attachment,
execution, rendering, and publication phases retain their existing explicit
cancellation checkpoints.

- For preparation, the generated sidecar is installed first and the complete
  canonical bundle is installed last as the point of no return. Cancellation
  before the bundle write leaves no successful preparation; a later identical
  invocation reconciles complete matching sidecar bytes and publishes or
  reuses the same bundle.
- Before the marker, cancellation prevents a published result. A later
  identical invocation reuses complete matching files and ignores/cleans
  abandoned per-file staging bytes. A file is installed at its deterministic
  final name only after the complete temporary bytes are synced and verified.
- After the marker, cancellation cannot turn a committed result into a false
  cancelled response; the runtime revalidates and returns the committed
  result.
- Repeated identical invocations return byte-identical artifacts.
- Existing differing bytes fail closed as a publication conflict or tamper.
- A marker with a missing or partial artifact set fails closed.

This is cooperative, restart-reconcilable single-output publication. It is not
a claim of distributed exactly-once execution.

Per-file staging names are ephemeral implementation details, are removed
before a successful response, and never enter the bundle, report identities,
or deterministic output directory name. They are not run directories.

## Visual resource

The run output is promoted as a catalog asset; its `report.html` is the current
host-supported **Open visual report**. The response also exposes a
`flowblind-report://sha256/...` verification authority bound to the HTML,
verification marker, and preparation bundle hashes. The package-local resource
reader reopens and revalidates the commit marker, JSON, Markdown, HTML,
preparation identity, protocol identity, source identities, and attested
software identity before returning HTML bytes. It never reads the source
dataset or uses a mutable `file://` link.

The pinned Discovery schema does not declare custom URI-resolver registration.
Therefore the custom authority is not claimed to be directly host-clickable
until a separately approved resolver integration exists.

Generic Markdown and HTML are neutral. They present descriptive values and
typed evidence states without a robustness, acceptance, clinical, solver, or
globally-best-region verdict. VISC-specific narrative remains available only
to the separately reviewed exact VISC identity in the historical guided
runtime.

Vector/time readiness never turns missing wall evidence into a wall-shear
value, never substitutes timestamp samples for frame-average exposure,
never computes unstructured or temporal derivatives, never temporally
aggregates divergence/vorticity/strain/wall shear, and never treats coverage
or numerical-range failures as success. Complete-cycle membership is the
closed declared interval; endpoint tolerance gates acceptance and does not
change membership.

## Typed refusal codes

The v1 structured refusal object is:

```json
{
  "status": "refused",
  "error": {
    "code": "attachment-set-invalid",
    "classification": "input-validation",
    "detail": "A public, redacted explanation."
  },
  "containsResults": false
}
```

The v1 codes are:

- `attachment-set-invalid`
- `attachment-path-unsafe`
- `attachment-changed-during-read`
- `source-not-fully-hydrated`
- `legacy-sidecar-not-trusted`
- `candidate-sidecar-mismatch`
- `sidecar-invalid`
- `source-structure-invalid`
- `capability-metadata-mismatch`
- `capability-preparation-mismatch`
- `preparation-bundle-invalid`
- `preparation-build-mismatch`
- `preparation-bundle-source-mismatch`
- `human-context-mismatch`
- `package-attestation-failed`
- `confirmation-required`
- `run-failed`
- `verification-failed`
- `source-identity-mismatch`
- `output-artifact-tampered`
- `output-publication-partial`
- `concurrent-publication-conflict`
- `operation-cancelled`
- `unsupported-action`

Unsafe and unsupported scientific intents retain the existing reviewed
non-result statuses and reason-code precedence:

- `unsafe-unsupported`
- `needs-scientific-method`
- `unsupported`
- `ambiguous`

## External validation fixtures

WeatherBench2, paired-planar synthetic, and vector/time synthetic
materializations remain out-of-band release oracles with exact byte
identities. They are not runtime dependencies and authoritative fixture bytes
are not present in the candidate tree or copied into the package. The two
portable synthetic examples use
different names and bytes (and the vector example also uses different
dimensions); package validation refuses an example whose hash equals either
authoritative external synthetic fixture. Synthetic
release sources may be regenerated only from the named deterministic
materializers and must still match their separately reviewed external metadata
oracles.

## Preservation boundary

This package does not modify, regenerate, replace, import, or depend on:

- the public `flowblindResearch` `1.1.3` runtime or lock;
- historical/frozen evidence;
- the guided v2 durable registry, receipts, process leases, or output tree;
- `discovery/agents/flowblind-validation-teammate`; or
- repository-root Git history at runtime.
