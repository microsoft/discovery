# chip-drc — Design Rule Check Agent

## Overview

Node-aware Design Rule Check agent driven by KLayout batch DRC, consuming the PDK Binding (DRC rule deck) and emitting a Common Design Envelope. DRC is a mandatory tapeout gate. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/drc/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`chip-drc` is defined in [tool.yaml](tools/drc/tool.yaml). Its Docker build context is `tools/drc/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/drc/Dockerfile --tag chip-drc:local tools/drc
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


## Qualified Magic runtime

The Services image in `services-deployment.json` installs upstream Magic
**8.3.693**, pinned to commit `9fd4ee57386c08346b20389a55e4eb9d32553979`.
The canonical Containerfile verifies the archive SHA-256 and builds with
`make -j1`; prior worker and other-engine layers remain unchanged.
Native version/current-SKY technology loading and the retained wide/sliver
controls passed their expected discriminators on 2026-11-16: both engines clean
for the wide geometry; the sliver fails with one KLayout `m1.1` violation.
This bounded regression is not full-chip signoff or staged App activation.

Node-aware **Design Rule Check (DRC)** agent. Runs **KLayout** and/or **Magic**
batch DRC on a GDS/OASIS/DEF layout and reports the violation count with a
per-rule breakdown and waiver adjudication.

DRC is a **mandatory tapeout gate**: zero un-waived violations to sign off.

- **Engines:**
  - KLayout — `klayout -b -r <deck> -rd input=<layout> -rd report=<db>`
  - Magic — `magic -dnull -noconsole -rcfile <magicrc>` running `drc check`
- **Node awareness:** node-aware — the KLayout deck (`drc_rules`) and the Magic
  tech (`magicrc`/`magic_tech`) come from the PDK Binding; no node rules live in
  agent logic.
- **Output:** Common Design Envelope (`/output/final_results.json`).

## Why two engines (sky130 / open PDKs)

On sky130 the PDK ships DRC decks for **both** Magic and KLayout under
`libs.tech/{magic,klayout}`, and they catch **complementary** rules — neither
alone is a complete signoff. This agent therefore supports an `engine` selector:

| `engine` | Behavior |
|---|---|
| `both` (default when a Magic tech/rcfile is bound) | Run KLayout **and** Magic; clean only if **both** are clean. |
| `klayout` | KLayout deck only. |
| `magic` | Magic tech-driven DRC only. |

The residual un-waived violation count across **all** engine runs drives the
verdict, and per-engine counts + an engine-namespaced per-rule breakdown are
reported in `signoff_evidence`.

## PDK tool policy (recommended tools + settings)

Which engines to run and their per-engine settings are treated as **PDK
recommendations**, not agent logic. If the binding carries a `tool_policy.drc`
block, it is the authoritative default:

```jsonc
"pdk_binding": {
  "tool_policy": {
    "drc": {
      "engines": ["klayout", "magic"],   // recommended engine set
      "mode": "all_must_pass",           // how to combine
      "settings": {
        "klayout": { "threads": 8, "deck_vars": { "metal_top": "met5" } },
        "magic":   { "magicrc": "<ref>", "drc_euclidean": true }
      }
    }
  }
}
```

Resolution precedence for **every** engine/setting decision:

1. **Explicit caller param** (e.g. `engine`, `threads`) — highest.
2. **`tool_policy.drc`** — the PDK's recommendation (the normal path).
3. **Tool built-in default** — last resort.

The source of each decision is recorded (`signoff_evidence.engine_selection`,
`provenance.settings_source`). If a caller **overrides** the PDK-recommended
engine set, the run is allowed but returns `pass_with_caveats` with the override
recorded in `provenance.policy_override` — never silently. This keeps the "node
is a swappable binding" invariant: a different PDK that recommends a different
engine set changes only the binding, not this agent.

## Scenario

| Scenario | Purpose |
|---|---|
| `drc_check` | Run the node DRC deck(s) on a layout, count violations per rule/engine, adjudicate waivers, emit a pass/fail verdict. |

## Validated on the official sky130A deck

The KLayout engine was run end-to-end with the **official sky130A KLayout DRC
deck** (`libs.tech/klayout/drc/sky130A_mr.drc`, fetched via volare) on a **real
sky130 standard cell** (`sky130_fd_sc_hd__inv_1`): the full deck executed (289-line
log, ~0.4 s) and correctly reported **0 violations / clean**, as expected for a
foundry cell.

**Container-maintenance note:** the official sky130A **Magic** techfile requires
Magic ≥ 8.3.411, but the Debian apt package is 8.3.105 (2021), which cannot parse
the modern `extract` section. To run the Magic engine against the current sky130A
deck, build a newer Magic in the container (the KLayout engine is unaffected).

## Signoff discipline

Every waiver must name a `rule`, an `owner`, and a `justification` (a waiver rule
may be engine-namespaced `magic:<rule>` or bare). Only listed rules are waived;
the residual un-waived count across every engine drives the verdict. Engine
versions are recorded in `provenance`. An un-waived violation is never laundered
into a pass, and a failed engine invocation fails the whole check.

## PDK note

The KLayout deck (`drc_rules`) and Magic tech (`magicrc`/`magic_tech`) are supplied
by the PDK Binding. On sky130 these are the sky130 Magic and KLayout DRC decks;
switching nodes requires only a different binding.
