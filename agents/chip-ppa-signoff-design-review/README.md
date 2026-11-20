## Overview

Node-agnostic signoff and design-review agent that independently judges whether the accumulated Common Design Envelopes constitute a defensible signoff. It checks required-gate coverage, adjudicates waivers (owner + justification + rule-deck version), reports PPA against budget, and never launders an un-waived violation or an unjustified waiver into a pass. It consumes envelopes and never re-runs a flow stage.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/design-review/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/python:3.13-slim-bookworm`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`design-review` is defined in [tool.yaml](tools/design-review/tool.yaml). Its Docker build context is `tools/design-review/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/design-review/Dockerfile --tag chip-ppa-signoff-design-review:local tools/design-review
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes

```yaml
asset_class: agent
canonical_name: PPA Signoff and Design Review Agent
flow_stage: I - Signoff and Review
node_awareness: node-agnostic
tier: 1
nature: reasoning / orchestrated
required_tools:
- Design Review Tool
required_skills:
- Verification and Validation Skill
- Design Review Skill
- QoR Reporting Skill
- Provenance Skill
supported_problems:
- signoff readiness / evidence-sufficiency review
- required-gate coverage check
- waiver adjudication (owner + justification + rule-deck version)
- PPA-vs-budget review
emits: Common Design Envelope
```

# PPA Signoff and Design Review Agent

Services deployments append the source-controlled
[Services overlay](services-instructions.md) to `agent.yaml` instructions.
The fixed action has no `params_file` or `params_json` function argument:
mount the parameter resource at `/input/params.json`. Additional cited evidence
files must be mounted at their stated input paths. Failed-job `CDE_JSON=` logs
retain the actual native verdict; framework success alone is not signoff.

**Purpose** — Independently judge whether the accumulated Common Design Envelopes
constitute a defensible signoff: every required gate has evidence, every waiver is
justified and owned, PPA meets budget, and no un-waived violation or unjustified
waiver is laundered into a pass.

**Responsibilities** — Evidence-sufficiency review; required-gate coverage check;
waiver adjudication (owner + justification + rule-deck version); PPA-vs-budget
review; verdict with confidence and residual risk.

**Supported problems** — Signoff readiness review; required-gate coverage; waiver
adjudication; PPA-vs-budget review.

**Required tools** — Design Review Tool (Common Design Envelope review + waiver
adjudication; emits a Common Design Envelope).

**Required skills** — Verification and Validation Skill, Design Review Skill, QoR
Reporting Skill, Provenance Skill.

**Inputs** — A set of Common Design Envelopes from upstream stages; the list of
required signoff gates; optional PPA budget and waiver list.

**Campaign rulings** — Open `campaigns/<slug>/policy/human-rulings.json` when
present. Accepted known conditions stay visible as caveats with approver,
timestamp, justification, and residual risk; acceptance never changes a truthful
detector finding into a clean result.

**Outputs** — Covered vs missing gates; un-waived violation count; invalid-waiver
list; PPA vs budget; a signoff verdict with confidence and residual risk. All
outputs conform to the Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the reviewed envelopes,
the gate coverage, the adjudicated waivers, and the verdict so the decision is
auditable without re-reviewing. It consumes envelopes but does not re-run any flow
stage.

**Validation gates**

- Every claimed gate has evidence; missing required gates are un-signoff-able.
- A real un-waived violation forces `fail`.
- Every waiver carries an owner, a justification, and a rule-deck version; an
  invalid waiver yields at best `pass_with_caveats`, never `pass`.
- Provenance present (node binding is `none`; node-agnostic).

**An empty `required_gates` list is not a satisfied one.** Without it, coverage
is checked only against the mandatory tapeout floor this catalog documents —
DRC, LVS and antenna, which together gate GDS assembly — and the verdict is
capped at `not_assessable`, because whether *this* design also needed CDC,
low-power, DFT, formal or STA-corner gates was never stated and cannot be
inferred from the envelopes alone. Supply `required_gates` to obtain a `pass`.

**Violation counts are read independently.** The reviewer parses each envelope's
own metrics (`results.unwaived_violations.value` and the gate-specific totals
that DRC, LVS, antenna, STA and CDC publish) rather than trusting the verdict the
producing stage assigned itself — trusting it would make the review a
restatement. A violation-counting gate whose count cannot be read is reported as
`unreadable_violation_counts` and caps the verdict at `not_assessable`: an
unreadable count is not a clean one.

## Position in the flow

The independent adversarial gate at the end of the flow. Where the Cross-Run QoR
Analytics Agent *tracks* trajectories, this agent *judges* signoff readiness on a
single design: it consumes the hashed, reproducible Common Design Envelope every
agent already emits and renders a defensible pass / pass_with_caveats / fail. It
is deliberately independent of the agents that produced the evidence.

## Node-Specific Notes

None. Node constants live in the envelopes under review; this agent is
node-agnostic and introduces none.

## Standalone execution (1.2.0)

Build `tools/design-review/Dockerfile` with `tools/design-review` as context.
No shared launcher, software installation or host source paths are required.
The fixed action is `python3 -B -u /app/run.py --params-file /input/params.json`.
Attach one UTF-8 JSON object with an explicit supported `scenario` and nonempty
`envelopes` array. Objects such as `budget` stay inline. Envelope paths and
resolvable cited artifact paths must remain inside immutable `/input`, including
after symlink resolution. Aliases, command JSON, duplicate keys, malformed JSON
and nonfinite values are rejected. No opportunistic input-file discovery occurs.

Use read-only root and `/input`, networking off, fresh writable persistent
`/output` and `/workdir`, and persistent scratch mounts at `/tmp`, `/var/tmp`,
`/home/worker`, `/run` and `/dev/shm`. Existing output/workdir contents cause
failure rather than reuse. Root runtime directory environment overrides are ignored.
The self-contained `/output/common_design_envelope.json` lists output-relative
artifacts; evidence actually consumed is copied under `results/evidence`.
The native required-gate, unwaived-fail and waiver-adjudication rules remain:
`completed/fail` exits 1, as do invalid inputs. Native `review`,
`not_assessable` and `pass_with_caveats` remain visible (exit 0 is transport
completion, not unconditional chip signoff). Unreadable waiver counts are
`not_assessable`, not zero or a traceback. Only failures log
`CDE_JSON=<json>`, parsed directly from the actual persisted envelope.

Run packaged tests with `python3 -B -m unittest discover -s /app/tests -v`,
setting `DESIGN_REVIEW_TEST_ROOT` to a fresh persistent directory under `/workdir`.
Tests use only synthetic fixtures; no fixture result constitutes real chip signoff.
