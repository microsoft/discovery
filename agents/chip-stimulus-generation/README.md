## Overview

Node-agnostic stimulus generator that produces directed and constrained-random stimulus targeted at coverage goals and corner cases from the shared verification plan (vplan). Generation is seeded pseudo-random sampling with bounded rejection sampling for relational blocks -- there is no SMT/CSP solver. Non-conforming samples are dropped rather than emitted, and the shortfall gates the run.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/stimulus-generation/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/python:3.13-slim-bookworm`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`stimulus-generation` is defined in [tool.yaml](tools/stimulus-generation/tool.yaml). Its Docker build context is `tools/stimulus-generation/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/stimulus-generation/Dockerfile --tag chip-stimulus-generation:local tools/stimulus-generation
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Stimulus and Constrained-Random Generation Agent
flow_stage: B - RTL Design and Verification
node_awareness: node-agnostic
tier: 2
nature: reasoning / orchestrated
required_tools:
- Stimulus Generation Tool
required_skills:
- Stimulus Generation Skill
- Verification Planning Skill
- Coverage Closure Skill
- Provenance Skill
supported_problems:
- constrained-random stimulus
- directed test generation
- coverage-directed test generation
- seed/regression stimulus management
emits: Common Design Envelope
```

# Stimulus and Constrained-Random Generation Agent

Services deployments append the source-controlled
[Services overlay](services-instructions.md) to `agent.yaml` instructions.
The fixed action takes no JSON interpolation or parameter-path argument;
mount the returned parameter resource at `/input/params.json`. Read native
artifacts and retain failed-job `CDE_JSON=` evidence.

**Purpose** — Generate directed and constrained-random stimulus targeted at
coverage goals and corner cases.

**Responsibilities** — Constraint/randomization modeling; directed-test authoring;
coverage-directed stimulus generation; seed management; corner-case targeting.

**Supported problems** — Constrained-random stimulus; directed test generation;
coverage-directed test generation; seed/regression stimulus management.

**Required tools** — Stimulus Generation Tool (seeded pseudo-random sampling +
bounded rejection sampling; no SMT/CSP solver).

## The tool never emits stimulus that violates its constraints

Three independent paths used to emit non-conforming transactions, each reporting
`verdict: pass`:

1. the bounded rejection loop appended its last **still-rejected** transaction
   when it ran out of tries;
2. a soft constraint overwrote a field *after* sampling with no re-check — a
   field declared `0..9` could emit `9999`;
3. a field with no declared domain sampled as literal `null`.

All three now pass through one **exit gate**: every transaction is re-checked
against the full constraint set immediately before emission, and a violating
sample is dropped and counted rather than emitted.

This matters because emitting illegal stimulus is worse than emitting none. The
DUT is exercised with input it was never required to handle, and either it
misbehaves — a phantom bug that costs a debug session — or it tolerates it, and
coverage is credited to bins that legal stimulus never reached.

### Satisfiability is witness-based

Emitting *N* conforming transactions **proves** the constraint set satisfiable:
each one is a witness. Exhausting the rejection budget proves nothing — a narrow
but perfectly legal constraint exhausts the same way a contradictory one does.
So `constraints_solvable` is `true` only when witnessed, and `null` (unknown)
otherwise. It is never reported as "unsatisfiable", and raising
`max_rejection_tries` is the correct response to a shortfall on a rare-but-legal
constraint.

Contradictions that *are* statically provable — a block requiring a value the
field's own domain cannot produce, or a distribution/soft value outside the
declared range — are caught before sampling, with an explanation rather than an
unexplained shortfall. Contradictions **across** blocks are not statically
detectable and are caught by the runtime gate instead.

**Required skills** — Stimulus Generation Skill, Verification Planning Skill,
Coverage Closure Skill, Provenance Skill.

**Inputs** — RTL and interfaces; verification plan (`vplan`) and coverage holes;
constraint model; seeds.

**Outputs** — Generated stimulus/test set; targeted-hole mapping; seed ledger;
expected coverage contribution. All outputs conform to the Common Design Envelope
and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the stimulus set, the
coverage holes each test targets, seeds, and constraints so coverage closure is
measurable without re-deriving intent.

**Validation gates**

- `stimulus_shortfall == 0` — every requested transaction was generated AND
  conforms. A shortfall means the run did not produce the stimulus the test plan
  believes it produced.
- Every test maps to a `vplan`/coverage target.
- Seeds recorded for reproducibility.
- Provenance present (node binding is `none`; node-agnostic).

**Known limits** — No SMT/CSP solver: constraints are sampled and checked, not
solved, so a legal-but-narrow constraint may exhaust the rejection budget and
report a shortfall. Raise `max_rejection_tries` before concluding anything about
satisfiability. Coverage-directed generation forces supplied hole values and
re-checks each generated transaction, but does not simulate the DUT or prove
coverage closure. Supplied directed tests are preserved as authoring input;
the random-generator conformance gate is not a claim about these supplied tests.

## Shared verification plan (`vplan`)

Part of the verification cluster that consumes the immutable shared `vplan`. This
agent consumes open coverage holes (from the Functional/Code Coverage agents) and
generates stimulus, proposing updates in output evidence rather than modifying input.

## Standalone package contract (1.2.0)

Build from `tools/stimulus-generation` with its own `Dockerfile` (the identical
`Containerfile` remains a compatibility filename). Only Python stdlib and local
helpers are needed; no shared family runtime or dependency installation.

The action is fixed:
`python3 -B -u /app/run.py --params-file /input/params.json`.
Create and mount a JSON resource at that path; action parameters contain no
shell-interpolated JSON. `params.schema.json` describes the mounted payload.
The native wrapper also accepts one explicit JSON object argument for direct
tests, never aliases, HTML quote repair or fallback to another file after errors.
Parameter and optional `vplan_file` paths must resolve under `/input`.
Objects must be inline, ranges integer, count positive, explicit seeds nonempty
integer arrays, weights finite/nonnegative with positive total, and rejection
budget nonnegative. Missing seeds retain generated-and-recorded legacy behavior;
use explicit seeds for deterministic replay.

Configure read-only root and `/input`, network off, and caller-owned persistent
writable mounts at `/output`, `/workdir`, `/tmp`, `/var/tmp`, `/home/worker`,
`/run`, `/dev/shm`. Output/workdir must be empty for each operation; stale
directories exit 2 without overwriting evidence. Input bytes are never changed,
and environment variables cannot redirect output/work paths.

CDE: `/output/common_design_envelope.json`; stimulus reference:
`results/stimulus.json`, relative to `/output`. Exit 0 accepts only completed
with pass, pass_with_caveats or review. Review/caveats do not imply clean
signoff or measured DUT coverage. Invalid input, missing CDE, failed status and
completed/fail all exit nonzero. Failed Services jobs may omit output assets;
the failure-only `CDE_JSON=<json>` native log contains the actual persisted
envelope. This local package declaration does not register a Services/app action.

Run native tests without installing anything:
`python3 -B -m unittest discover -s tests -v`.
Set `CHIP_VALIDATION_EVIDENCE_ROOT` to an absolute writable evidence directory,
including in the packaged container (for example `/output/test-evidence`).
