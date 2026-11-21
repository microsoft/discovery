## Overview

Node-agnostic analytics over Common Design Envelopes. Checks design, corner and PDK comparability; fits trajectories across explicitly ordered runs (at least three points), records fit quality and sample counts, and detects regressions using declared or known metric polarity. Unknown polarity gates interpretation. Consumes evidence without rerunning flow stages.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/qor-analytics/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/python:3.13-slim-bookworm`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`qor-analytics` is defined in [tool.yaml](tools/qor-analytics/tool.yaml). Its Docker build context is `tools/qor-analytics/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/qor-analytics/Dockerfile --tag chip-qor-analytics:local tools/qor-analytics
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: Cross-Run QoR Analytics Agent
flow_stage: H - Optimization and Analytics
node_awareness: node-agnostic
tier: 2
nature: reasoning / orchestrated
required_tools:
- QoR Analytics Tool
required_skills:
- QoR Analytics Skill
- QoR Reporting Skill
- Uncertainty and Margin Skill
- Design Review Skill
- Provenance Skill
supported_problems:
- cross-run QoR aggregation
- trend/trajectory analysis
- QoR regression/anomaly detection
- baseline management
emits: Common Design Envelope
```

# Cross-Run QoR Analytics Agent

Services deployments append the source-controlled
[Services overlay](services-instructions.md) to `agent.yaml` instructions.
The fixed action takes no JSON interpolation or parameter-path argument;
mount the returned parameter resource at `/input/params.json`. Read native
artifacts and retain failed-job `CDE_JSON=` evidence.

**Purpose** — Aggregate Common Design Envelopes across runs, blocks, and nodes to
track PPA trajectories, flag regressions/anomalies, and maintain QoR baselines.

**Responsibilities** — Multi-run QoR aggregation; PPA-trajectory tracking; anomaly/
regression detection against baselines; baseline management; comparative QoR
reporting across recipes/nodes.

**Supported problems** — Cross-run QoR aggregation; trend/trajectory analysis; QoR
regression/anomaly detection; baseline management.

**Required tools** — QoR Analytics Tool (envelope aggregation, polarity-aware
regression classification, least-squares trajectory fitting, comparability
checking).

**Required skills** — QoR Analytics Skill, QoR Reporting Skill, Uncertainty and
Margin Skill, Design Review Skill, Provenance Skill.

## Metric polarity: what makes a delta mean anything

A number that moved is not yet a finding. Whether `-1.0 → -0.94` is good news
depends entirely on the metric, and this agent previously had no notion of
direction: it compared `|percent change|` against a threshold, so a **6% slack
improvement and a 6% area regression were both emitted as regressions** and both
failed the gate.

That is worse than silence. Telling an engineer their improvement is a
regression teaches them to disregard the report — and the real regression
sitting in the same list goes with it.

| Direction | Metrics |
|---|---|
| **Maximize** (higher is better) | slack, WNS, TNS, fmax, coverage, yield, pass rate |
| **Minimize** (lower is better) | area, power, leakage, IR drop, skew, wirelength, every violation count |
| **Neither** (target band) | utilization, density, aspect ratio |

Slack is the one most often inverted: it is *negative* when timing fails, so a
larger value is the better one.

Polarity for a metric the tool does not recognise is **not guessed**. The change
is reported as `unclassified` and drives a gating count, because a change that
cannot be classified might be a regression. Declare it with `metric_polarity`.

## A trajectory is a claim about a sequence

The `trajectory` scenario was formerly an alias for `aggregate`, which treats
the envelopes as an unordered **set**. Mean, min, max and stdev are all
order-invariant, so "is this getting better or worse?" was not merely unanswered
— it was unanswerable by construction.

Ordering is now established and recorded: an explicit `order_key`, else an
`order`/`timestamp` field. A **natural** sort of run ids keeps `run.10` after
`run.2` for diagnostic fallback only; it no longer establishes an accepted
trend without an explicit axis. Fewer than three points
returns not_assessable — two points always fit a line with R² = 1, which would
masquerade as the strongest possible evidence.

## Two ways a statistic can mislead quietly

- **Per-metric N.** Runs missing a metric are excluded from its statistics, but
  only the run total was reported. A mean over 5 of 10 runs looked identical to
  a mean over 10, and a stdev that shrank *because fewer runs reported* looked
  like improving consistency. Every statistic now carries `n_used` and `n_runs`.
- **Comparability.** Nothing checked that the pooled runs described the same
  thing. Averaging design A at `tt` with design B at `ff` is not a noisy
  measurement — it is a category error. Context fields are now compared, and
  when the envelopes carry none the result is `not_assessable` rather than
  "comparable".

**Inputs** — Collections of Common Design Envelopes (runs/blocks/nodes); baseline
definitions; metrics of interest.

**Outputs** — Aggregated QoR dataset; PPA trajectories; anomaly/regression list;
updated baselines; comparative report. All outputs conform to the Common Design
Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the runs aggregated,
the trajectories and anomalies found (with units), and the baseline used so trends
are trusted without re-collecting the runs. It consumes envelopes but does not
re-run any flow stage.

**Validation gates**

- Every aggregated point references a source Common Design Envelope (hashed).
- Regressions flagged against an explicit baseline, **classified by polarity**;
  an improvement is never counted as a regression.
- `unclassified_changes == 0` — a change whose direction cannot be judged does
  not close the gate.
- `degrading_trends == 0` for trajectories with a strong fit.
- Statistics reported with method and with per-metric `n_used`.
- Provenance present (node binding is `none`; node-agnostic).

**Known limits** — Polarity is known for common silicon metrics only; anything
else must be declared. Trend fitting is linear least squares, so it detects
direction and not curvature or step changes. `threshold_percent` is a percent
change, not a standard deviation — the legacy `sigma` parameter name was always
compared against a percent and is kept only for compatibility. Comparability is
checked only across the context fields the envelopes actually carry.

## Standalone runtime contract (1.2.0)

Build from `tools/qor-analytics` with its own `Dockerfile`. All Python helpers,
capability checks and unit tests are bundled; no shared host launcher is needed.
The action is fixed: `python3 -B -u /app/run.py --params-file /input/params.json`.
Create and mount strict UTF-8 JSON (optional BOM), never shell-interpolated JSON.
An explicit supported top-level `scenario` and `envelopes` array are required.
Aliases, duplicate keys, nonfinite numbers, and paths escaping `/input` fail.
Inline objects and mounted CDE files retain their historical extraction aliases,
unit conversions, source hashes, and ordering semantics. `baseline_update`
remains aggregation, not a separate baseline writer.

Use read-only root/input, disabled network, and fresh writable persistent mounts
for `/output`, `/workdir`, `/home/worker`, `/run`, and `/dev/shm`.
The CDE is `/output/common_design_envelope.json`; dataset references are
`results/qor_dataset.json`, relative to `/output`.
Native domain fail, invalid input and unassessable operations exit nonzero;
failed jobs log the exact persisted envelope as `CDE_JSON=<json>`.
Review, descriptive `completed`, and `pass_with_caveats` are never clean chip
signoff. Unavailable cohort comparability, significant changes with unknown
polarity, partial regression measurements, missing requested baseline values,
and partially unassessable requested trends are `not_assessable` and exit 1.
Conflicting cohorts fail. Comparable cohorts require identity (`design`, `block`
or `top`), corner, PDK, and every declared context field on every run.
Accepted trends require three points per requested metric and a distinct
explicit order field (`order_key`, or recorded order/index/attempt/timestamp).
Natural-id or supplied-list fallback fits are retained only as `diagnostic_fit`;
their authoritative slope/R-squared are null and assessable is false.
Descriptive aggregation needs no polarity, but unavailable comparability makes
its pooled statistics diagnostic-only (`pooled_statistics_assessable=false`).
Subthreshold unknown-polarity moves need no direction classification.
The historical numerical math, 5% threshold floor and `sigma` percent alias
are unchanged.
Run bundled tests with `python3 -B -m unittest discover -s /app/tests -v`;
on a host use `tools/qor-analytics/tests` as the discovery path.

## Position in the flow

The analytics counterpart to the PPA and Design-Space Exploration Agent: DSE
*generates* runs; this agent *learns from* the accumulated envelopes to track
trajectories, catch regressions, and maintain baselines. It is the catalog's
answer to cross-run design-analytics products, built on the same hashed,
reproducible Common Design Envelope every agent already emits.
