## Overview

Node-aware constraints agent driven by the OpenROAD/OpenSTA tool set. Authors SDC from derived netlist structure plus caller-supplied timing intent, lints the result in the same run, and measures constraint coverage against the enumerated endpoint population. Never defaults a clock period, I/O budget or exception. Consumes the PDK Binding and emits a Common Design Envelope. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/constraints/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-constraints` is defined in [tool.yaml](tools/constraints/tool.yaml). Its Docker build context is `tools/constraints/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/constraints/Dockerfile --tag chip-constraints-sdc:local tools/constraints
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Constraints (SDC) Agent
flow_stage: C - Synthesis, DFT, Constraints
node_awareness: node-aware
tier: 1
nature: reasoning / orchestrated
required_tools:
- Constraints Tool
required_skills:
- Constraint (SDC) Authoring Skill
- Timing Closure Skill
- PDK Binding Skill
- Provenance Skill
supported_problems:
- SDC authoring
- constraint linting
- clock-domain and I/O budget definition
- exception management
emits: Common Design Envelope
```

# Constraints (SDC) Agent

**Purpose** — Author and validate timing/design constraints (SDC) for the target
node and clocking plan.

Clock-source enumeration follows native OpenSTA forward reachability from actual
top-level inputs to register clock pins, including clock buffers; direct-net
connections are retained too. Structural candidates are not timing
intent: periods, I/O budgets, slew, latency and loads must still be supplied.
An unavailable native graph query is not an empty, successfully checked cone.

**Responsibilities** — Clock definition; I/O timing; false/multicycle paths; clock
groups; constraint linting against the PDK.

**Supported problems** — SDC authoring; constraint linting; clock-domain and I/O
budget definition; exception management.

**Required tools** — Constraints Tool (OpenSTA-based SDC authoring, lint and
coverage measurement).

**Required skills** — Constraint (SDC) Authoring Skill, Timing Closure Skill, PDK
Binding Skill, Provenance Skill.

## What this agent derives vs. what it must be told

The division below is the whole design of this agent. Getting it wrong in either
direction is a defect: refusing to derive what is derivable makes the agent
useless, and inventing what is not derivable makes it dangerous.

| Derived from the netlist (OpenSTA introspection) | Must be SUPPLIED (spec / budget / user) |
|---|---|
| which ports drive register clock pins (traced through the net) | the clock **period** |
| the endpoint population (the coverage denominator) | the input/output **delay budget** |
| how many clocks the SDC actually defines, read back from the solver | which paths are genuinely **false** |
| the input and output port lists | **multicycle** intent and its multiplier |

An unsupplied number is never guessed. It is returned as a named **hole**, the
constraint is not emitted, and the verdict is `not_assessable`.

### Why a period is never defaulted

An invented clock period is the most dangerous artifact this flow can produce.
Synthesis targets it, CTS balances to it, STA closes against it, ECO repairs to
it, and signoff blesses it — and every one of those gates reports **success**.
The design is then silently either unbuildable or far slower than intended, and
no downstream check can recover the fact that nobody ever chose the number. A
hole is loud and cheap; a fabricated period is silent and expensive.

### The round trip

Authoring and linting happen in the **same run**: the tool writes the SDC and
immediately reads it back through OpenSTA. The tool therefore never emits
constraints it has not itself checked, and every emitted line carries a comment
recording whether it came from derived structure or supplied intent, and from
which source.

### Exceptions require attribution

A `set_false_path` is refused unless it carries **both** a reason and a source.
Where a CDC signoff run is available, its crossing ID is the correct source — that
agent enumerates exactly the crossings that legitimately warrant an exception.
Note the converse limitation: a *required but absent* exception is as much a
defect as an unjustified one, and no downward count of exceptions can detect it.

### Coverage is measured, not keyword-counted

`unclocked_indicators` counts phrases in an OpenSTA report, so "no complaints"
and "nothing was examined" look identical to it. Enumerating the design supplies
the missing denominator. When the population cannot be established the result is
reported as `not_assessable` with null counts — **never** as zero.

**Inputs** — Specification/clock plan; netlist or RTL; PDK Binding (library units,
default corners).

**Outputs** — Validated SDC; constraint-coverage report; exception ledger. All
outputs conform to the Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope with the SDC, the clocks and
exceptions declared, the corners referenced, and unconstrained-path coverage.

**Validation gates**

- No unconstrained register-to-register or I/O paths (or explicitly justified).
  A non-zero `unclocked_indicators` count is a **fail**, not a caveat.
- `unsupplied_intent_holes` is zero when authoring (gating).
- Exceptions justified with both a reason and a source.
- Units from the PDK library.
- Node binding and provenance present.

**Known limits** — Coverage depends on OpenSTA introspection succeeding; if the
solver cannot enumerate the design, coverage is `not_assessable` rather than
clean. Clock-group and generated-clock authoring are not implemented; supply
those in a hand-written SDC and lint it. Exception *absence* is undetectable:
no count of declared exceptions can reveal one that should have been written.

## Node-Specific Notes

Liberty and units are consumed from `pdk_binding`, never hard-coded.

### sky130 (validation baseline)

- `pdk`: `sky130A`; `stdcell_library`: `sky130_fd_sc_hd`
- Units: capacitance pF, time ns (from Liberty); corners tt/ss/ff
- Engine: OpenSTA (bundled in the OpenROAD image); `engine_class: oss`

### <future node> (stub)

- `pdk`, `stdcell_library`, `liberty`, `corners`, `units`: _from binding_.
