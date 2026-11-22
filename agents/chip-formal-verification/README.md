# chip-formal-verification — Formal Verification Agent

## Overview

Node-agnostic formal-verification agent driven by the Yosys sat engine (the back-end SymbiYosys wraps), running bounded model checking / k-induction of SV assertions and emitting a Common Design Envelope.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/formal-verification/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/debian:12-slim@sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`formal-verification` is defined in [tool.yaml](tools/formal-verification/tool.yaml). Its Docker build context is `tools/formal-verification/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/formal-verification/Dockerfile --tag chip-formal-verification:local tools/formal-verification
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


Node-agnostic **formal-verification** agent. Runs bounded model checking (BMC) of
SystemVerilog `assert property` statements via the **Yosys `sat`** engine — the
formal back-end that SymbiYosys wraps — with an optional **k-induction** unbounded
prove.

- **Engine:** Yosys formal (`prep` + `sat -prove-asserts -seq <depth>`; `-tempinduct` for prove)
- **Node awareness:** node-agnostic (no PDK binding).
- **Output:** Common Design Envelope (`/output/final_results.json`).

## Scenario

| Scenario | Purpose |
|---|---|
| `prove` | BMC the assertions to `depth` cycles (`mode=bmc`), or prove unbounded via k-induction (`mode=prove`). |

## Proof discipline

A BMC pass proves the properties **only to the requested depth** — the agent says
so explicitly and never claims an unbounded proof unless a k-induction prove
succeeds. A counterexample is a hard fail.
