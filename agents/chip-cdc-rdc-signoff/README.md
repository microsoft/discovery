## Overview

Node-agnostic CDC/RDC signoff using Yosys and optional bounded formal checks. Enumerates crossings, checks synchronizers, and treats each multi-bit bus as one coherency obligation. Missing gray/handshake/qualifier/FIFO schemes fail closed. Formal evidence covers source-domain obligations only, to the recorded depth; metastability settling and reconvergence remain structural.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/cdc-rdc/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/debian:12-slim@sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`cdc-rdc` is defined in [tool.yaml](tools/cdc-rdc/tool.yaml). Its Docker build context is `tools/cdc-rdc/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/cdc-rdc/Dockerfile --tag chip-cdc-rdc-signoff:local tools/cdc-rdc
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Clock- and Reset-Domain-Crossing (CDC/RDC) Signoff Agent
flow_stage: B - RTL Design and Verification
node_awareness: node-agnostic
tier: 1
nature: reasoning / orchestrated
required_tools:
- CDC/RDC Tool
required_skills:
- Clock/Reset Domain Crossing Skill
- RTL Design Skill
- Verification and Validation Skill
- Provenance Skill
supported_problems:
- CDC signoff
- RDC signoff
- synchronizer verification
- reconvergence analysis
emits: Common Design Envelope
```

# Clock- and Reset-Domain-Crossing (CDC/RDC) Signoff Agent

**Purpose** — Sign off clock-domain-crossing (CDC) and reset-domain-crossing (RDC)
structures as a first-class gate, not a lint side-effect.

**Responsibilities** — CDC/RDC structural analysis; synchronizer recognition and
verification; multi-bit bus coherency screening (per-bit synchronization of a
multi-bit value is a defect, not a fix); declared source and selected destination
protocol obligations;
multi-clock/multi-reset formal modeling; waiver review.

**Supported problems** — CDC signoff; RDC signoff; synchronizer verification;
multi-bit bus coherency; reconvergence analysis.

**Required tools** — CDC/RDC Tool (Yosys structural analysis + SymbiYosys/
yosys-smtbmc/z3 bounded model checking for declared coherency obligations).

**Required skills** — Clock/Reset Domain Crossing Skill, RTL Design Skill,
Verification and Validation Skill, Provenance Skill.

**Inputs** — RTL; clock/reset definitions and domain map; synchronizer library;
optional per-signal `bus_protocols` declaring the multi-bit coherency scheme
(gray/handshake/qualifier/fifo); optional waivers.

**Outputs** — CDC/RDC violation database by class; synchronizer inventory;
clean/dirty verdict; waiver ledger. All outputs conform to the Common Design
Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope with per-class CDC/RDC
violation counts, the synchronizer inventory, the domain map used, and a signoff
verdict.

**Validation gates**

- Every crossing classified and synchronized or waived.
- No un-waived CDC/RDC violations for signoff.
- Domain map recorded.
- Provenance present (node binding is `none`; node-agnostic).
- Every requested formal task returns `PASS`; unknown, error, timeout, cancelled,
	and not-assessable results block closure.
- Every safety implication has a reached activation cover.
- Multi-clock and multi-reset proofs consume `clock-reset-domain-map/v2`; intent
	is never inferred from names or topology.

## Formal modes

The mandatory formal matrix runs bounded counterexample search, induction, and
activation covers. Fairness-backed `live` mode is additive and available only when a crossing
declares an eventual response, fairness signal, and written fairness justification.
Counterexample VCD, Yosys witness, Verilog testbench, SMT constraints, solver logs,
and per-task statuses remain under `formal/` in the output.

`formal_scope=source` proves Gray/handshake source obligations and supports v1.
`multiclock` and CDC `full` require v2 clock intent. `multireset` and RDC `full`
require v2 reset intent. Related clocks use declared periods/phases; asynchronous
clocks use independent symbolic phases. A stoppable clock requires
`max_idle_ticks`, an explicit bounded-progress assumption.

Supported crossing protocols are `level`, `pulse`, `toggle`, `gray`, `handshake`,
`qualifier`, `mcp`, `fifo`, `async_fifo`, and `reconvergence`. Unencoded
declarations fail as not assessable. Digital formal does not establish analog
metastability resolution, library recovery/removal timing, or electrical reset-tree
pulse integrity.

The generated obligations are deliberately explicit: Gray source transitions;
handshake/qualifier/MCP source-data hold windows; bounded level convergence;
no-spurious pulse/toggle destination events; FIFO pointer Grayness plus local
overflow/underflow guards; and declared reconvergent-bundle coherence. Eventual
delivery is proved only when the declaration supplies a response and fairness
contract and enables additive `live` mode. These templates do not, by themselves,
prove arbitrary FIFO payload ordering or analog first-stage settling.

## Task identity binding

Raw tool output always reports `provenance.task_identity_state` as
`host_finalization_required` — only the Discovery host, via
`catalog/finalize_cde.py`, may promote it to `verified` against
`stage_task_identity.canonical_stamp`. A caller-authored `run_id` or any other
self-asserted identity is `rejected_untrusted_tool_stamp` and fails closed:
prior-cohort envelopes carry recycled task ids that now denote entirely
different tasks, so CDE trust binds only to the host-finalized, authenticated
execution record, never to an agent-chosen key.

## Relationship to sibling agents

The RTL Design Agent performs *structural* CDC identification during elaboration;
this agent owns *signoff* — a named gate with per-class counts, synchronizer
verification, reconvergence analysis, and a waiver ledger — judged by the PPA
Signoff and Design Review Agent.
