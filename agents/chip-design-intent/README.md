# chip-design-intent — Design Intent and Requirements Agent

## Overview

Node-agnostic design-intent / requirements agent: normalizes requirements into a machine-checkable specification and allocates PPA budgets with closure checking. Deterministic, no external engine. Emits a Common Design Envelope.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/design-intent/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/python:3.13-slim-bookworm`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`design-intent` is defined in [tool.yaml](tools/design-intent/tool.yaml). Its Docker build context is `tools/design-intent/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/design-intent/Dockerfile --tag chip-design-intent:local tools/design-intent
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


Node-agnostic **design-intent / requirements** agent. Deterministic structured
spec authoring — **no external engine**.

- **Node awareness:** node-agnostic — no PDK binding consumed.
- **Output:** Common Design Envelope (`/output/common_design_envelope.json`).

## Standalone worker and action contract

The source-controlled [Services overlay](services-instructions.md) is appended
to `agent.yaml` instructions for Services deployment. Its mounted-file and
failure-log contract is part of this source package, not a cloud-only patch.

`tools/design-intent/Dockerfile` is self-contained, using Python 3.13 and only
this package's vendored helpers. The original `Containerfile` remains a historical
family-builder baseline; it is not the standalone build entry point. No image
build, deployment or registration is implied by these source files.

Create UTF-8 JSON at mounted `/input/params.json`, following
`tools/design-intent/params.schema.json`. The fixed action is
`python3 -B -u /app/run.py --params-file /input/params.json`; its local input schema
has no interpolation arguments. **Actual Services actions** auto-add `inputMounts`,
`nodePool` and `outputMounts`; callers still must create and mount the parameter
file. The local app does **not** register an action from this declaration alone.
Use an available registered action and its actual schema, not an invented one.
For the Services action bound to Foundry function `chip-design-intent-run`,
use `WriteResource` to create the JSON resource with a unique filename, then
mount its returned file URI at `/input/params.json` through the actual action's
`inputMounts`. The resource's unique name need not be `params.json`; that is the
fixed container mount destination. Do not pass JSON as a shell argument.
This is actions-based integration; no `code_environments` entry is required.

Mount `/input` read-only. Provide fresh empty writable `/output` and `/workdir`
and persistent writable mounts for `/tmp`, `/var/tmp`, `/home/worker`, `/run` and
`/dev/shm` when running with a read-only root filesystem. Configure `/dev/shm`
explicitly rather than depending on an implicit runtime mount. The entrypoint
does not create or modify `/input`. Nonempty output or work directories are
refused with exit 2 without overwriting their contents.

Parameters require an explicit supported top-level scenario. Malformed JSON,
explicit malformed values, escaping parameter-file paths (including symlinks),
and missing/unknown scenarios fail closed with a persisted failure CDE and exit
1. No alternate file, HTML unescaping, quote rewriting or alias fallback occurs.
A single raw JSON argv remains available for direct compatibility only, never
the Services action; apostrophes and Unicode quotes are preserved exactly.

Artifacts live in `results/specification.json` or `results/ppa_budget.json`, with
`reports/REPORT.md` and the root CDE. Envelope artifact references are relative
to `/output`. Exit 0 requires persisted `completed` and verdict `pass`,
`pass_with_caveats` or `review`; completed/fail is nonzero. Review and caveats
are valid authoring outcomes, **not engineering signoff**. No integration reserve
is invented: omit `integration_reserve_pct` for the existing review outcome, or
declare a finite percentage in `[0, 100)` for explicit allocation closure.

The worker closes the CDE file before invoking the local narrative report
renderer, then organizes artifacts. Report rendering uses only Python/string
formatting and filesystem writes, not a network/model call. A report exception
is logged without replacing the CDE verdict. A Services operation remaining
Running after `wrote /output/REPORT.md` does not by itself identify a worker
hang or prove remote CDE availability; transport and terminal state need their
own evidence.

Failed Services jobs may return `outputData: []` even when the worker saved the
CDE. On nonzero exit with an available CDE, the worker emits one marked
`CDE_JSON=<json>` log line by reading the persisted envelope. If output artifacts
are unavailable, retrieve retained native logs and parse that line as JSON to
recover the actual status, verdict, validation note, error and trace (when
present). The file remains unchanged. Do not substitute a framework success or
error message for the native verdict, and do not infer pass when neither artifact
nor marked CDE log is available. A reused-directory refusal with no new CDE does
not emit a marked line from historical artifacts.

Example parameter file (not an action argument):

```json
{"scenario":"normalize","requirements":[{"id":"DR-1","text":"The counter's latency shall be < 5 ns"}]}
```

Native regression uses stdlib unittest, writing evidence exclusively under the
campaign's `outputs/design-intent-package` directory:

```powershell
python3 -B -m unittest discover -s agents-docker\chip-design-intent\tools\design-intent\tests -v
```

For packaged `/app/tests`, mount a writable evidence directory and set
`CHIP_VALIDATION_EVIDENCE_ROOT=/evidence`, then invoke
`python3 -B -m unittest discover -s /app/tests -v`. This explicit absolute
location takes precedence over the host session fallback, which is available
only within the actual source-package directory structure. Every test creates
an exclusive fresh evidence subdirectory.

## Scenarios

| Scenario | Purpose |
|---|---|
| `normalize` | Normalize raw requirements into a machine-checkable spec: **stable, non-positional identifiers**, inferred categories, measurable acceptance criteria, and flags for non-measurable / duplicate requirements. |
| `ppa_budget` | Allocate a top-level PPA target (`area_um2` / `power_mw` / `freq_mhz`) across weighted blocks and check the allocation **closes** additively against the target. |

## Requirement identifiers

An identifier is a promise: **that this name keeps pointing at this requirement.**
Every downstream citation — a vplan item, a coverage bin, a waiver — depends on
that promise holding across every edit to the spec.

- **A caller-supplied `id` is authoritative and used verbatim.** Pass requirements
  as objects (`{"id": "DR-7", "text": "..."}`) and the tool will not rename them.
- **Identifiers are never derived from position.** Inserting or reordering a
  requirement does not re-point existing ids at different requirements.
- **Where no id is supplied, one is derived from the requirement text** and
  reported as tool-assigned; the verdict is `pass_with_caveats`. Adopt those ids
  into the spec — a derived id changes if the text is edited, whereas an id that
  lives in the document is stable across revisions.
- **A duplicate or malformed id is a gating defect**, reported rather than
  silently renamed: auto-renaming would re-point one of them, which is precisely
  the failure the check exists to catch.

**Limit, stated plainly:** the tool sees one revision per run. It cannot detect an
identifier retired in an earlier revision, nor one recycled onto a different
requirement between runs. Carrying ids in the spec document is what makes
identity stable across revisions.

## Units are part of the value

A field called `area_um2` **records an intention, not a fact.** Nothing about the
name stops a value in mm2 being written into it, and **a number wrong by a factor
of a million looks exactly like a number that is right** — correct type, correct
field, and it propagates cleanly through every downstream calculation. That is
what makes this a gate rather than a warning.

Every budget target is parsed into an explicit (magnitude, unit) pair and
converted to a canonical unit — um2 for area, mW for power, MHz for frequency:

| Supplied | Recorded | Was |
|---|---|---|
| `{"area_um2": "12 mm2"}` | 12000000 um2 | 12 |
| `{"freq_mhz": "1.2 GHz"}` | 1200 MHz | 1.2 |
| `{"area_um2": "1e6 um2"}` | 1000000 um2 | 1 |

**Refused rather than coerced:** a unit of the wrong dimension (`"5 ns"` into an
area field); a value with no unit in a field whose name states none (bare
`area`); prose that does not begin with the quantity (`"under 50 mW at 1.2 GHz"`,
which previously resolved to whichever field it was written into).

A bare number in a unit-suffixed field — `{"area_um2": 12000}` — is the normal way
to call the API and is accepted, but recorded as an **assumed** unit so a reader
can tell it from an observed one.

**Block weights must be non-negative.** A negative weight allocates a negative
budget, and closure cannot catch it: the parts still sum to the target.

**In requirements**, a threshold with no unit (`"latency shall be < 5"` — less
than five *what*?) satisfies the measurability gate, so it is counted separately
and reported as **advisory**: genuinely dimensionless requirements exist (counts,
ratios, error budgets), and only a reviewer can say which a given one is.

## Discipline

Every requirement should be measurable (a unit or comparison operator); the agent
flags non-measurable and duplicate requirements rather than silently accepting
them. A PPA budget must close against the top-level target — an allocation that
does not close is a fail.
