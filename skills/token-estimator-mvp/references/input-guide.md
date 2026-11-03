# Shared inputs and interpretation

The [contract](../resources/contract.schema.json) and
[shared core](../scripts/model.js) use version 1.2.0 and still accept input
versions 1.0.0 and 1.1.0.

## Input guidance

Required root fields: `contractVersion` and nonempty `tasks`. Each task needs
unique `id` and either `description` or `profileId`.

| Input | Meaning |
|---|---|
| `scopeDescription` | Overall summary, never a multiplier |
| `description` / `profileId` | Deliverable or justified work class |
| `phaseId` | Optional refinement |
| `count` | Distinct comparable deliverables, default one |
| `bounded:true` | Confirms comparable task/session scale |
| `bounded:false` or omitted | Conditional one-task/session planning base |
| `depth` | `bounded` or `unresolved` |
| `validation` | `included`, `separate-tasks`, or `unresolved` |
| `readiness` | `ready`, `not-ready`, or `unresolved` |
| `retryLimit` | Nonnegative operational scope limit |
| `monitoring` | `startup-only`, `bounded`, `ongoing`, or `unresolved` |
| `monitoringChecks` | Positive count; requires `monitoring:"bounded"` |
| `nonOverlap:true` | Explicitly disjoint work units for aggregation |
| `concurrency` | Scheduling metadata only |

Never request user token guesses. Invalid input is an error.

## Work and optional phase selection

All six classes support coarse planning without requiring a phase:

| Class | Coarse comparison basis |
|---|---|
| `evidence-assessment` | Existing assessment-style session band |
| `literature-screening-synthesis` | Existing screening/extraction session band |
| `tool-verification-analysis` | Existing verification pilot band |
| `simulation-development-execution` | Envelope of implementation/correction/sweep alternatives |
| `prediction-development-validation` | Envelope of synthetic/real-data/integration alternatives |
| `existing-workflow-operation` | Existing instruction/setup/launch/startup allowance |

For class-level results, the model uses the minimum lower and maximum upper of
comparable phase bands. These are alternatives, not additive workflow totals.

## Existing-workflow operations

"Execute an existing workflow" covers AI instruction/input review, local
command preparation, launch or blocked handoff, and startup/status/error
confirmation. It does not include scientific-model development or external
resource-time estimation.

Unknown readiness can still return a conditional base. Ongoing monitoring,
open-ended repair, or undefined bounded-monitoring checks remain unresolved
additions.

## Output boundaries

`perUnitTokens` and `listedTaskTokens` are comparison bases. `totalTokens:null`
means full listed scope is unknown, not zero.

`knownSubtotalTokens` can be present when only part of scope is calibrated.
`wholeInvestigationTokens` is always null.

Provenance is intentionally compact and public-safe. It reports model/range
method and generic reference observation metadata only.
