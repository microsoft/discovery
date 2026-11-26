# Benchmarks and reproduction scope

This directory publishes **inputs and guidance**, not the original private run
stores or native transcripts. [VALIDATION-HISTORY.md](VALIDATION-HISTORY.md) is a
retrospective summary of original **0.2.0** observations dated **2026-11-22**.
Relocation and 0.2.1 packaging do not rerun or reauthenticate those observations.

The implementation reconstructs cases and diagnostics independently from the
[CFD Forge paper](https://arxiv.org/abs/2610.14104). It does not redistribute Forge
code/data/containers or claim bit-reproduction of that campaign.

## Separate validation layers

| Layer | Public recipe/input | What it can establish |
|---|---|---|
| Deterministic/fixture tests | [Core tests](../tests/test_core.py) and the entry test suite | Check/policy/extraction behavior on supplied inputs, not new CFD |
| Paper-style campaign | [Campaign](../tools/openfoam/src/discovery_physics/benchmarks/run.py), [case generators](../tools/openfoam/src/discovery_physics/benchmarks/cases.py) | New Foundation solves and decisions under the fixed-rule proposer |
| Supplemental S8 | [Study recipe](../tools/openfoam/src/discovery_physics/benchmarks/study_s8.py) | A separately registered three-grid cross-run assessment |
| Held-out CLIO | [Prompts](heldout/prompts.json), [harness](../scripts/heldout.py) | Behavioral compliance, including clarification/refusal and confirmation stops |
| Deterministic A/G comparison | [Comparison](../tools/openfoam/src/discovery_physics/benchmarks/comparison.py) | Finite fixed-rule/forced-ACCEPT gate controls |
| Benchmark Markdown summary | [Report](../tools/openfoam/src/discovery_physics/benchmarks/report.py) | Presentation of existing campaign inputs, not independent verification or final HTML delivery |
| Raw B/C reviews | [Native model comparison](../scripts/model_comparison.py) | Advisory model judgments on paired packets, not live verdict authority |
| Local service/MPI/fixtures | [Path checks](../scripts/live_paths.py), [fixture generator](../scripts/fixture_probe.py) | Selected execution/extraction paths, not cloud dispatch or general physical validity |

Successful process exit, all behavioral checks passing, all member runs accepted,
and a study being accepted are different statements. Missing evidence and unknown
checks do not count as passing predictions. Model diagnoses remain advisory.

## Prerequisites and output policy

Use [installation](../docs/installation.md) for the host runtime and explicit
development dependencies, plus workspace skill installation for native CLIO
workflows. Historical support is Windows x64, Python 3.11+, Discovery
0.15.21-preview, and observed `claude-sonnet-5`; other environments need their own
qualification. Install and authenticate external products independently.

Select the current user's existing **absolute project root** explicitly; never
infer it from CWD, Git, runtime installation or source acquisition. In a multi-root
workspace ask only if the intended project is ambiguous. Initialize a marked
`results-<slug>-<utc>-<suffix>/` direct child before authoring/freezing new benchmark
work, using the [results helper](../skills/phy-openfoam/scripts/project_results.py).
Keep generated inputs, scripts, logs, analyses, exports, HTML and native artifacts
inside it, never under any project `agents` directory or anywhere in acquired
contribution source, even staged elsewhere. Curated examples/reviewed fixtures
remain contribution assets; private runtime app data stays separate.

Keep the selected run/study stores and original HMAC key available for local
verification without moving the key into results. Record source revision,
original native paths and run/study IDs in the manifest. Do not overwrite
original outputs or repurpose historical receipts as current evidence. Native
sessions, RPC logs, absolute paths, and confidential geometry are not automatically
public-safe. Sanitized derivatives require new artifact identity, source hashes,
and transformation provenance.

Resource limits fail closed by default. Harnesses must not unconditionally enable
exceptions. Where offered, `--allow-unenforced-limits` is an explicit
**operator-only** flag; otherwise inherited operator configuration applies. An
agent must not enable an exception, increase concurrency, or reconfigure engines
to complete a benchmark. Omission of the flag does not cancel an already saved
operator exception; disclose actual effective resource-limit evidence.

## Suggested new-run sequence

After operator preflight and approval, use the project-results initialization and
`Invoke-ResultsPython` prelude in the [script reference](../scripts/README.md).
It selects the explicit `$project` and read-only `$entry`, initializes `$work`
with `init --project-root <absoluteproject> --slug <slug>`, then runs developer
modules in a child with CWD at results and child-only
`DISCOVERY_PHYSICS_RUNS=<results>/runs`. It also keeps generated temporary files
and bytecode/cache output out of source, without changing HOME, runtime config,
signing keys, resource caps or shared solve slots. The native CLI-only `run`
wrapper is not an arbitrary Python-module launcher. Source validation requires
**both** tools/openfoam/src and the entry root ahead of inherited `PYTHONPATH`
in that child, selecting the candidate package and its scripts namespace.
Non-editable installed benchmark modules do not change when source is edited.
The documented launcher uses existing dependencies without a pip reinstall,
host-runtime patch or image update; it does not update installed CLI/worker code.

```powershell
$campaign = Join-Path $work 'analysis/paper-campaign'
$s8 = Join-Path $work 'analysis/s8-study'
$receiptInputs = Join-Path $work 'analysis/verification-inputs'
$packets = Join-Path $work 'analysis/packets'
$checks = Join-Path $work ('analysis/checks-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $checks | Out-Null
Invoke-ResultsPython -m pytest (Join-Path $entry 'tests') `
	-o ("cache_dir=" + (Join-Path $checks 'pytest-cache')) `
	--basetemp (Join-Path $checks 'pytest-temp') --junitxml (Join-Path $checks 'tests.xml')
Invoke-ResultsPython -m discovery_physics.benchmarks.run `
	--project-root $project --results-dir $work --out $campaign --parallel 2
Invoke-ResultsPython -m discovery_physics.benchmarks.study_s8 `
	--project-root $project --results-dir $work --out $s8 --parallel 2
# Verification expects both unsigned receipt sets in one explicit read-input tree.
if (Test-Path -LiteralPath $receiptInputs) { throw 'Choose a fresh verification-input directory.' }
Copy-Item -LiteralPath $campaign -Destination $receiptInputs -Recurse
Copy-Item -LiteralPath (Join-Path $s8 'S8_study.json') -Destination (Join-Path $receiptInputs 'S8_study.json')
Invoke-ResultsPython (Join-Path $entry 'scripts/validation_receipts.py') `
	--project-root $project --results-dir $work --results $receiptInputs `
	--out (Join-Path $work 'analysis/verified.json')
Invoke-ResultsPython -m discovery_physics.benchmarks.comparison `
	--project-root $project --results-dir $work --results $campaign --out $packets
Invoke-ResultsPython -m discovery_physics.benchmarks.report `
	--project-root $project --results-dir $work --results $campaign `
	--comparison (Join-Path $packets 'summary.json') --out (Join-Path $work 'exports/benchmark-summary.md')
```

Every benchmark writer requires `--project-root`, marked `--results-dir` and a
fresh `--out`; a run-store override alone is insufficient. Campaign and S8
writers each require a **new directory**, so do not pass the campaign directory
to the subsequent study writer. The combined unsigned receipt-input copy above
preserves both originals and their embedded paths; the receipt verifier's one
`--results` input requires all campaign JSON and the supplemental S8 JSON.
Comparison reads the campaign; the Markdown report accepts its explicit
`--results`, optional existing `--comparison` summary JSON and fresh `--out`.
It does not replace final HTML or independently verify recorded decisions.
Keep harness work/output roots and all test temporaries within marked results;
the fresh checks parent must exist before pytest creates its disposable base-temp
directory. Use fresh destinations for each attempt, retaining all prior failures.
The initializer's `--exact` refuses collisions; its `check --project-root
<absoluteproject> --results-dir <markedresults> [--destination <path>]` is read-only.
No results metadata or resource override is added to the runtime config model.

These are instructions for a **new** campaign, not commands executed by this
documentation pass. Inspect every per-case error, verdict, and verified lineage;
do not use a successful exit alone as a campaign-pass signal. Record the actual
source revision, Python/dependency versions, image ID, Foundation build, operator
settings, exceptions, commands, timings, and unexecuted coverage.

The campaign invokes no model: it uses the fixed-rule proposer through the same
scientific gates. The supplemental study is separate from original S8, whose
single-run coverage did not establish mesh independence. Comparison packet
generation includes independently constructed diagnostic faults; those are not
additional new CFD solves.

## Optional native workflows

See [script commands](../scripts/README.md) for each parser's required routing
and fresh output. Native CLIO `run` takes a positional prompt plus `--out` and
`--cwd`, not a positional output. Held-out `run` and `score` both require JSON
`--out`; their optional `--work-root` is respectively new receipts work or
existing score input. Model-review `collect` requires `--packets`, existing
`--source` protocol/inputs and `--work` native batch directory, plus a **new**
derivative `--out`; it never writes back into the original review. Path checks
require a JSON `--out`; fixtures require a fresh export-directory `--out`.
`DISCOVERY_CLIO_EXE` or the supported `--clio-executable`
option selects an independently installed native runtime.
`DISCOVERY_CLIO_STATE_HOME` selects the comparison inspector's native state root;
it does not configure where CLIO writes sessions.

Held-out `score` and model-comparison `collect` inspect existing receipts without
new model calls or CFD. They cannot reproduce a private original campaign from
source prompts alone. Scoring must inspect terminal behavior and relevant
verified records rather than keyword matches or prose claims. H14's historical
stop is not permission to resume a substitute without consent.

For a status-only question, inspect the original recorded native path directly,
including legacy external stores: one read-only chat snapshot, no initializer,
write-producing wrapper/logs, new HTML, reassessment or timer. Explicit report
packaging may read a legacy `--runs-root`, but requires `--project-root` and
exactly one of existing marked `--results-dir` or new `--slug`. Optional `--out`
requires `--results-dir` (not `--slug`) and stays within that same container,
outside signed stores, with no overwrite of
individual report files; rerender into a fresh `reports/v2` subdirectory.
See [reporting](../docs/reporting.md).

For B/C review, freeze the protocol/packets before model calls, use fresh input-only
sessions and a new output directory, retain every attempt, and withhold truth
until all responses are complete. B includes gate outputs; C removes outcomes,
thresholds, and objective coverage. Keep paired aliases, full answer coverage,
native response-model provenance, and tool-policy audits. Blinding by working
directory/policy is not OS-enforced isolation or a cross-model performance study.

## Public evidence and claim limits

Original benchmark outputs, receipts, and transcripts are private historical
evidence, retained byte-identically whether in a legacy ignored location or a
separately approved project-results archive. They are excluded from public
distribution because of absolute paths and native session metadata. Public docs
do not link to those private locations.
The retrospective summary is not a live receipt, a public HMAC signature, or a
complete independently verifiable archive.

An approved unsigned report/archive copy uses the supplied
[migration helper](../skills/phy-openfoam/scripts/migrate_results.py); a legacy
archive uses `--archive` after preflight confirms no journals, keys, configuration
or links. It defaults to copy-only into new marked results. Optional separately
approved `--remove-source` cleanup follows whole-source inventory and copied-file
hash verification. Preserve old receipt bytes, relative-reference dependencies,
native references, scope and failure history; the new manifest records original
paths/hashes. No signed native history or keys move, and no CFD or renewed
scientific authentication is implied. See [reporting](../docs/reporting.md).

Exported archives and published hashes do not automatically include omitted
fields, code, ancestors, study members, keys, or externally retained chain heads.
Do not publish secret keys to fill that gap. Independent review needs a clearly
scoped evidence package or a new campaign with retained native artifacts.

No benchmark described here establishes actual Azure dispatch, production
CPU/memory/PID enforcement, cloud-study integration, or commercial production
sign-off. See [deployment readiness](../docs/deployment.md) and
[distribution rules](../docs/distribution.md).
For service output, `/output` remains the platform-managed mount. Host/platform
publication must materialize returned artifacts into explicit project results
where available; a host path is not a container path or a new cloud action.
Disclose missing publication support rather than silently reroute execution.