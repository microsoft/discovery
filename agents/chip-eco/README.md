# Signoff ECO Agent

## Overview

Node-aware signoff ECO agent. Sits between signoff STA rung-1 and a rung-2 reopen: clusters violating paths, adjudicates whether a targeted ECO can close the gate, and drives bounded, checkpointed, reversible repair waves via OpenROAD repair_timing / repair_design under scoped set_dont_touch. Escalates on plateau. Validated on SkyWater sky130.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/eco/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/openroad/orfs@sha256:ee88641037a1c8e3403203bdca2b6256bf44a7957fa26719c8463ba638d76f9d`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`eco` is defined in [tool.yaml](tools/eco/tool.yaml). Its Docker build context is `tools/eco/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/eco/Dockerfile --tag chip-eco:local tools/eco
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


## Overview

`chip-eco` helps a timing-closure engineer decide whether a signoff miss is
suitable for a targeted engineering change order (ECO) or requires reopening an
upstream implementation stage. It clusters violating paths, identifies dominant
fix sites, and executes one bounded, checkpointed repair wave at a time.

The agent does not treat ECO as an alternative to resolving a structural cause.
A concentrated, repairable cluster can justify a wave; a missing pipeline stage,
an inaccessible macro-internal fix, or an exhausted repair response requires an
upstream reopen. A completed tool invocation is not a chip-signoff verdict.

The catalog records SkyWater sky130 as its validation baseline. Adding this
documentation does not constitute a new simulation, physical run, or validation
of another node.

## Architecture

The prompt definition is [agent.yaml](agent.yaml), the catalog identity is
[metadata.yaml](metadata.yaml), and the packaged tool definition is
[tools/eco/tool.yaml](tools/eco/tool.yaml).

The tool's [entrypoint](tools/eco/run.py) accepts a single-line JSON object
through the `params_json` action parameter. It can also read a scenario-bearing
JSON file from the read-only input mount. The two scenarios are:

1. **`analyze_violations`:** parse an OpenSTA `report_checks` report, cluster
   violations, separate frozen hierarchy, rank candidates and screen ECO entry.
   This is pure analysis; it does not edit the design or invoke a repair engine.
2. **`eco_wave`:** validate inputs and any requested explicit swaps/buffers,
   checkpoint the incoming DEF, scope eligible instances, run the repair and
   routing chain, refresh extraction/timing, compare measured check classes and
   commit or roll back exactly one wave.

[tools/eco/eco_utils.py](tools/eco/eco_utils.py) owns the repair and judgement
logic. [tools/eco/path_cluster.py](tools/eco/path_cluster.py) owns report parsing
and the entry screen. The reasoning agent chooses the next fix set and wave
budget from the recorded response; the tool does not run an autonomous sequence
of waves.

Global routing is incrementally bracketed around the repair, but detailed
routing is a full run per wave. Standard-cell fill is removed and restored in
the wave. Post-ECO metal fill and full downstream signoff are separate stages.

## Prerequisites

- A Discovery/Copilot execution context that can invoke the packaged `eco` tool
  and a model deployment for `{{CHAT-MODEL}}`.
- For `analyze_violations`, an existing OpenSTA `report_checks` text report.
  Supply the clock period and total endpoint population when interpreting
  scale-relative entry thresholds.
- For `eco_wave`, a consistent routed DEF, SDC, baseline timing report,
  technology LEF, standard-cell LEFs and Liberty views. Inputs must describe the
  same design/corner and be readable inside the tool container.
- A resolved `pdk_binding`, including node-specific filler cells, supply names,
  routing/RC inputs and any clock-buffer or threshold-voltage capabilities used.
- OpenROAD with the required resizer, routing, extraction and timing commands.
  The source recipe uses the shared physical image family, not an independently
  available base image.
- Read-only input/PDK mounts, a writable output directory and separate disposable
  scratch space. Never mount the original source tree or signed-off campaign
  evidence as writable tool output.

### Source-checkout image build

The local recipe intentionally has an invalid default for `CHIP_PHYSICAL_BASE`.
It must be built through the canonical family plan, which supplies the inspected
base and provenance digest. A bare per-tool build without those inputs will not
work.

From the source checkout, the documented family workflow is:

```powershell
python -B agents-docker\shared\build_docker.py --check --run-id <run-id>
python -B agents-docker\shared\build_docker.py --run-id <run-id>
```

The second command builds all 43 selected tools with their shared bases; it is
not a single-agent smoke test. Use an isolated build environment and the governed
family configuration. Do not replace tagged developer images during publication
testing. The family builder and base definitions are workspace prerequisites,
not files bundled inside this agent. A community export must resolve and test
that public build/dependency chain separately.

## Configuration

### Agent and tool interface

| Setting | Meaning |
|---|---|
| `{{CHAT-MODEL}}` | Model deployment supplied by the caller/deployer. |
| `params_json` | Single-line, double-quoted JSON with a required `scenario`. |
| `pdk_binding` | Node-specific views, RC inputs, cells and capabilities; explicit parameters override corresponding binding fields. |
| `frozen_prefixes` / `dont_touch` | Independently signed-off macro, pad-ring and hard-IP exclusions. |

The local source tool definition contains workspace-specific build metadata.
Publication staging relocates unsupported local fields and adds deploy-time
tool-ID wiring without changing the original source definition.

### Analysis parameters

| Parameter | Required | Meaning/default |
|---|---|---|
| `scenario` | Yes | `analyze_violations`. |
| `sta_report` | Yes | Existing OpenSTA report path. |
| `clock_period_ns` | No | Clock period in nanoseconds; needed for period-relative screening. |
| `total_endpoints` | No | Full endpoint population, not just violating paths. |
| `path_type` | No | `max` or `min`; omission includes both. |
| `top` | No | Number of ranked candidates, default `20`; this is an integer here. |
| `frozen_prefixes` | No | Hierarchy scopes that this level cannot modify. |
| `thresholds` | No | Explicit overrides for provisional entry-screen priors. |

### Wave parameters

| Parameter | Required | Meaning/default |
|---|---|---|
| `scenario` | Yes | `eco_wave`. |
| `top` | Yes | Design identifier; unlike analysis `top`, this is a string. |
| `def_file`, `sdc` | Yes | Existing routed design and timing constraints. |
| `baseline_sta_report` | Yes | Existing pre-wave report; missing baseline fails before repair. |
| `tech_lef`, `liberty` | Yes | Explicitly supplied or resolved from `pdk_binding`. |
| `cell_lef` | Design-dependent | Library/macro LEFs needed to load the design; scalar or list. |
| `spef`, `rc_rules` | Recommended | Existing parasitics and extraction rules, directly or from the binding. |
| `baseline_drv_report` | Recommended | Pre-wave electrical-violation report for comparable DRV judgement. |
| `baseline_route_drc_report` | Recommended | Pre-wave route DRC evidence. |
| `baseline_clock_skew_report` | Recommended | Pre-wave clock balance evidence. |
| `target_instances` | Recommended | Eligible repair cluster; omission is unscoped. |
| `wave_index` | No | Output ordinal, default `0`; use a fresh output directory per invocation. |
| `repair_classes` | No | Default `drv_pre`, `setup`, `hold`, `drv`, in that order. |
| `repair_tns` | No | Breadth from `0` to `100`; default `0` repairs the worst endpoint only. |
| `max_repairs_per_pass` | No | Default `1`. |
| `aggression` | No | `conservative`, `moderate`, or `aggressive`; default `conservative`. |
| `max_displacement` | No | Explicit incremental-placement displacement bound in sites. |
| `power_net`, `ground_net` | No | Defaults `VDD`/`VSS`; pass the actual node names. |
| `filler_cells` | Recommended | Explicit or binding-derived physical cells for row continuity. |
| `repair_pdn_vias` | No | Default `true`; disabling it records a grid-check gap. |
| `max_paths` | No | Report cap, default `200`. |
| `timeout_s` | No | OpenROAD subprocess limit, default `7200` seconds. |

Additional supported controls include setup/hold margins, utilization and buffer
bounds, wire-RC layers, maximum wire length, a PDN-via repair layer, explicit
`resize_swaps`, explicit `buffer_insertions`, `clock_buffer_cells` and
`doctrine_deviation_justification`. Consult the tool definition and implementation
for their complete contracts. A swap is checked for logical-equivalence-set
membership before mutation; a clock-net buffer requires an explicit valid
clock-buffer list.

On typical sky130 standard-cell designs supply names are `VPWR`/`VGND`, not the
tool's generic defaults. Threshold-voltage moves depend on the bound library's
capabilities and must not be promised on a single-threshold library.

## Usage

1. Prepare a fresh, writable output location and mount only the required inputs
   read-only. Invoke the packaged `run` action, not hand-authored OpenROAD Tcl.
2. Start with analysis. The following JSON is the value of `params_json`; the
   report must already exist in the container input mount:

   ```json
   {"scenario":"analyze_violations","sta_report":"/input/sta.rpt","clock_period_ns":10.0,"total_endpoints":4200,"path_type":"max","top":20,"frozen_prefixes":["u_macro","u_pad_ring"]}
   ```

3. Inspect `results.entry_verdict`, ranked/frozen candidates, concentration and
   provisional-threshold caveats. `hard_reject` means escalate without spending
   a wave. `assess` means the screen permits further reasoning, not automatic
   ECO approval.
4. If the evidence supports an ECO, select a legal fix set and invoke one wave.
   This illustrative input requires the named design reports/views to exist;
   its numbers and instance names are not a verified fixture:

   ```json
   {"scenario":"eco_wave","top":"myTop","wave_index":1,"def_file":"/input/routed.def","sdc":"/input/myTop.sdc","spef":"/input/myTop.spef","baseline_sta_report":"/input/sta.rpt","baseline_drv_report":"/input/drv.rpt","baseline_route_drc_report":"/input/route_drc.rpt","baseline_clock_skew_report":"/input/clock_skew.rpt","target_instances":["u_glue/u_buffer"],"dont_touch":["u_macro","u_pad_ring"],"repair_classes":["drv_pre","setup","hold","drv"],"repair_tns":0,"max_repairs_per_pass":1,"aggression":"conservative","max_displacement":1,"power_net":"VPWR","ground_net":"VGND","pdk_binding":{"pdk":"sky130A","tech_lef":"/pdk/sky130.tlef","cell_lef":["/pdk/cells.lef"],"liberty":["/pdk/cells.lib"],"filler_cells":["sky130_fd_sc_hd__fill_1"]}}
   ```

5. Inspect the actual CDE, class deltas, judgement gaps, fix ledger, checkpoint
   and returned artifact references. A wave commits only when at least one
   measured class strictly improves and none regresses. Improvements are not
   restricted to timing: a measured DRV-only or route-DRC-only improvement can
   justify a commit.
6. Re-analyze the returned design's fresh timing before deciding another wave.
   Stop/escalate on a structural cause, churn at least as large as closure, or
   exhausted effort budget; never keep a regressing mutation to improve a
   headline number.
7. After convergence, require post-ECO logical equivalence, metal fill,
   parasitic-aware multicorner timing and applicable physical/power signoff.

## Tools

### `eco` / `run`

- **Input:** `params_json`, or an input-mounted JSON object with a `scenario`.
- **Primary output:** `/output/common_design_envelope.json` with `status`,
  `validation`, `results`, `qor_metrics`, `signoff_evidence` and provenance.
- **Supporting output:** artifacts grouped under `/output/results`,
  `/output/reports` and `/output/logs`; the generated report is organized under
  `/output/reports/REPORT.md`.
- **Wave artifacts:** ordinal-specific DEF/netlist/SPEF, baseline checkpoint,
  generated Tcl, engine log and timing/electrical/routing/grid reports. The CDE
  records artifact basenames; resolve them in the appropriate organized group.
- **Rollback:** `signoff_evidence.eco_def` names the unchanged checkpoint when a
  wave is rejected. Rejected mutation artifacts are quarantined with a
  `.rejected` suffix and must not feed downstream stages.
- **Failure behavior:** unusable parameters or engine failure emit failed
  evidence and a nonzero process result. Successful execution can still report
  a negative entry decision or a rolled-back wave.

`analyze_violations` normally yields a `review` verdict for an assessable case,
or a completed `fail` entry decision for a hard reject. An engine-completed
`eco_wave` reports `pass` only for a committed wave with measured setup/hold,
DRV, routing DRC and both power grids closed, no unmeasured/regressed comparison
classes, and nonempty re-extracted DEF/netlist/SPEF artifacts. Rollback or partial
closure remains `pass_with_caveats`. The signal `wire_rc_layer` is required even
with input SPEF, for newly created nets; existing extracted parasitics are not
replaced by placement estimates. The conservative sizing flag is `-skip_size_down`
on the qualified OpenROAD version. Always
inspect the scenario decision and remaining gaps; neither process exit zero nor
`status: completed` implies timing closure or tapeout readiness.

Reading a routed DEF does not restore GRT's transient route trees. The wave
reconstructs those trees using the bound routing-layer range before opening
incremental repair, then loads input SPEF without placement estimation.

## Known Limitations

- Entry thresholds are provisional practice priors, not calibrated guarantees
  for a node or design. Report counts and concentration depend on report scope.
- Report-derived TNS sums only the paths present in the report. The caller must
  establish matching corner/path-count settings for a sound before/after
  comparison; the tool does not verify that generating context.
- Missing pre-wave DRV, routing DRC or clock-skew evidence leaves named classes
  unjudgeable. An unavailable measurement is not a clean check.
- Minimum pulse width, minimum period and crosstalk/noise have no repair engine
  here and are reported as unavailable. Do not claim they were signed off.
- Supplied SPEF is read rather than replaced by placement estimation, and
  changed routing requires refreshed parasitics. Without suitable extraction
  inputs, estimated timing is not post-route signoff evidence.
- Detailed routing can dominate runtime even for a small repair wave. There is
  no incremental detailed-route mode to make every invocation inexpensive.
- Independently signed-off macros, the pad ring and vendor IP must remain
  frozen, especially when their internal netlists are timing-transparent in the
  parent database. A required macro-internal edit belongs in that macro's flow.
- This tool is not full equivalence checking, metal-fill closure, independent
  DRC/LVS/antenna closure or final multicorner signoff. Those downstream checks
  remain mandatory; a repair-wave result cannot replace them.
- The source checkout's shared physical base/build helpers and local schema
  extensions require a separate portable, validated community export. The
  documentation and schema-preparation steps do not build or smoke-test it.

## Support

The source catalog metadata lists `discovery-catalog@microsoft.com` and
[Discovery community support](https://github.com/microsoft/discovery/discussions/categories/bugs).
Confirm current publisher authority and contact details before public release.
Do not publish private design files or credentials with a support request.

Report security vulnerabilities through the repository's
[security policy](https://github.com/microsoft/discovery/blob/main/SECURITY.md),
not public issues or discussion threads.

## Contributing

Follow the [community contribution instructions](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md)
and [agent authoring guide](https://github.com/microsoft/discovery/blob/main/docs/authoring-guides/agent-authoring-guide.md).
Prepare changes in publication copies, run the current trusted schema/policy
checks and isolated tool tests, and submit a fork-based PR for maintainer review.
Do not change original agent/tool sources merely to run publication tests, and
do not weaken enforcement or label an unrun check as passing.