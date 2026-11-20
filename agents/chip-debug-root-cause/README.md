## Overview

Node-agnostic verification-failure debugger. Buckets failures by error signature, parses the VCD waveform for X-states, stuck signals and activity around the failure, reduces a failing stimulus by real delta debugging against an executed oracle, and establishes determinism by re-running the reproducer rather than by inspecting a seed field. Reports anything it could not execute or read as not_assessable.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/debug/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `cgr.dev/chainguard/python:latest-dev@sha256:cf00203e9a81f254f1cdefdc0b0b22527d2cfbe0a884610605443c81d8b084bd`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-debug` is defined in [tool.yaml](tools/debug/tool.yaml). Its Docker build context is `tools/debug/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/debug/Dockerfile --tag chip-debug-root-cause:local tools/debug
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Debug and Root-Cause Agent
flow_stage: B - RTL Design and Verification
node_awareness: node-agnostic
tier: 1
nature: reasoning / orchestrated
required_tools:
- Debug Tool
required_skills:
- Debug and Root-Cause Skill
- Verification Planning Skill
- Design Review Skill
- Provenance Skill
supported_problems:
- failure triage
- waveform root-cause analysis
- failure bucketing
- regression-failure reduction
emits: Common Design Envelope
```

# Debug and Root-Cause Agent

**Purpose** — Triage verification failures to a minimal reproducer and a ranked
root-cause hypothesis.

**Responsibilities** — Failure triage; waveform/trace analysis; failure
clustering/deduplication; minimal-reproducer reduction; root-cause hypothesis
ranking with evidence.

**Supported problems** — Failure triage; waveform root-cause analysis; failure
bucketing; regression-failure reduction.

**Required tools** — Debug Tool (VCD waveform parsing, ddmin delta debugging,
observed-determinism re-execution).

**Required skills** — Debug and Root-Cause Skill, Verification Planning Skill,
Design Review Skill, Provenance Skill.

## Three claims this agent makes only from observation

| Claim | How it is established | When it cannot be |
|---|---|---|
| where the design went wrong | parsing the VCD (X-states, stuck signals, activity before the failure time) | no/unreadable trace → `not_assessable`, and hypotheses fall back to log text with that stated |
| this reproducer is **minimal** | ddmin against an oracle that re-executes the test on each candidate subset | no oracle → no reduction claimed; the original test is returned labelled `is_minimized: false` |
| this reproducer is **deterministic** | re-running it N times and comparing normalized outcomes | no runnable command → `not_assessable`, never `true` |

### Why determinism is never inferred from a seed

For reduction commands containing `{input}`, determinism re-executes a
materialized copy of the reduced candidate after ddmin and deletion checks.
The CDE records that exact stimulus and whether it is the reduced or original
candidate; the literal template is never treated as an executable reproducer.

This agent previously reported `"deterministic": seed is not None` — a property
asserted from the presence of a field, with nothing ever re-run. A fixed seed is
necessary for determinism and nowhere near sufficient: uninitialised state,
wall-clock and PID entropy, hash and iteration order, thread scheduling and
simulator version drift all survive it. The cost of that claim is paid by an
engineer who sets aside an afternoon to debug a failure they were told
reproduces on demand, and then cannot reproduce it.

Note the asymmetry in the evidence: N agreeing runs **cannot** prove determinism
(a 1-in-1000 flake survives 5 runs), so agreement is reported with its N
attached; but a single disagreement **does** prove non-determinism, and is
reported as a definitive failure.

### Why a "command that never ran" is a distinct outcome

A missing or mistyped reproducer command fails identically on every attempt, so
the outcomes agree perfectly. Treated naively that reads as *deterministic*.
The tool pre-resolves the executable and reports `not_assessable` instead — the
difference between "this reproduces reliably" and "this never ran at all".

**Inputs** — Failing tests and waveforms/traces; RTL; regression logs; seeds.

**Outputs** — Failure buckets; reproducers with measured minimality and observed
determinism; waveform findings (X-states, stuck signals, pre-failure activity);
ranked root-cause hypotheses with evidence, each labelled by whether it came from
the waveform or from log text. All outputs conform to the Common Design Envelope
and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming failure buckets,
reproducers (with seeds and their observed determinism), and ranked hypotheses
with supporting evidence so a fix can proceed without re-triaging.

**Validation gates**

- Every failure bucketed.
- `determinism_runs_agreed` > 1 — established by re-execution. A null (never run)
  does NOT satisfy this gate and is not reported as deterministic.
- Hypotheses ranked with cited evidence, each attributed to waveform or log.
- Provenance present (node binding is `none`; node-agnostic).

**Known limits** — VCD only; FST is binary and is refused rather than
partially parsed. Reduction requires a runnable oracle. The tool does not drive
Verilator, Icarus or Yosys itself — it analyses the artifacts they produce and
re-executes the command the caller supplies. It does not compute a suggested fix
locus; it reports located evidence and leaves the fix to the engineer.

## Shared verification plan (`vplan`)

Part of the verification cluster; associates failure buckets with the `vplan`
features they affect so closure state stays accurate.
