# chip-rtl-lint — RTL Lint and Style Agent

## Overview

Node-agnostic RTL lint / style agent driven by Verible (verible-verilog-lint + verible-verilog-format), emitting a Common Design Envelope.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/rtl-lint/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: `docker.io/library/debian:12-slim`. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`rtl-lint` is defined in [tool.yaml](tools/rtl-lint/tool.yaml). Its Docker build context is `tools/rtl-lint/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/rtl-lint/Dockerfile --tag chip-rtl-lint:local tools/rtl-lint
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


Node-agnostic **RTL lint / style** agent driven by **Verible**.

- **Engine:** Verible (`verible-verilog-lint`, `verible-verilog-format`)
- **Node awareness:** node-agnostic — lint does not consume a PDK binding.
- **Output:** Common Design Envelope (`/output/common_design_envelope.json`).

## Scenarios

| Scenario | Purpose |
|---|---|
| `lint` | `verible-verilog-lint` over sources with optional `rules`/`ruleset`/`waiver_files`; reports violation count + per-rule breakdown. Zero => pass. |
| `format` | `verible-verilog-format --verify` per source; reports how many are not canonically formatted. |
| `lint_gate` | Combined DEFAULT lint and canonical formatting gate; both required for stage closure. |

## Ordinary local execution

This OpenSTA-style package contains `agent.yaml`, `metadata.yaml`, README and the
complete `tools/rtl-lint` Dockerfile context. No shared code or host launcher is
required. Discovery parent owns specialist activation and handoffs.

Use local `.github/skills/discovery-add-agents/SKILL.md` Steps 5/6 with
`$srcRoot` set to `agents-docker` and exactly the three selected role folders.
Do not refresh these local edits from upstream. Copy only to an absent destination:

```powershell
$name = 'chip-rtl-lint'
$dst = Join-Path (Get-Location) "discovery_catalog\$name"
if (Test-Path $dst) { throw "Destination exists: $dst" }
New-Item -ItemType Directory -Force discovery_catalog | Out-Null
Copy-Item -Recurse "agents-docker\$name" $dst
# Run the skill's Step 6 with $selected=@($name).
```

The Local branch only copies and generates companions/lazy image bootstrap:
**no YAML action registration or mount configuration occurs**. IDs are not callable
Copilot tools. Invoke `run` only if genuinely registered and these mounts are
available. Otherwise directly invoke one container, without a host runner.
The fixed action reads `/input/params.json`, described by
`tools/rtl-lint/params.schema.json`; it does not interpolate JSON into shell text.

Importer image: **`rtl-lint:latest`**. Inspect first; only if missing:
`docker build -t rtl-lint:latest agents-docker\chip-rtl-lint\tools\rtl-lint`.
After import the context is `discovery_catalog\chip-rtl-lint\tools\rtl-lint`.
Podman takes the same arguments. Installation, daemon readiness and context
selection belong to integration. Existing images are not refreshed after edits:
select a source-current tag explicitly, never silently use stale source.

PowerShell single-operation example, from project root:

```powershell
$op = Join-Path (Get-Location) ("results\rtl-lint-" + [guid]::NewGuid().ToString('N'))
if (Test-Path $op) { throw "Operation already exists: $op" }
New-Item -ItemType Directory $op -ErrorAction Stop | Out-Null
'input','output','work','tmp','var-tmp','home','run','shm','evidence' | ForEach-Object {
    New-Item -ItemType Directory (Join-Path $op $_) -ErrorAction Stop | Out-Null
}
# Copy only frozen final RTL to "$op\input"; this example expects dut.v.
'{"scenario":"lint_gate","sources":["/input/dut.v"],"ruleset":"default","format_gating":true,"indentation_spaces":2}' |
    Set-Content "$op\input\params.json" -Encoding utf8
docker run --rm --pull=never --read-only --network=none --cpus=2 --memory=4g --pids-limit=256 `
    --mount "type=bind,source=$op\input,target=/input,readonly" `
    --mount "type=bind,source=$op\output,target=/output" `
    --mount "type=bind,source=$op\work,target=/workdir" `
    --mount "type=bind,source=$op\tmp,target=/tmp" `
    --mount "type=bind,source=$op\var-tmp,target=/var/tmp" `
    --mount "type=bind,source=$op\home,target=/home/worker" `
    --mount "type=bind,source=$op\run,target=/run" `
    --mount "type=bind,source=$op\shm,target=/dev/shm" `
    rtl-lint:latest python3 -B -u /app/run.py --params-file /input/params.json `
    1> "$op\evidence\stdout.log" 2> "$op\evidence\stderr.log"
$containerExit = $LASTEXITCODE
$containerExit | Set-Content "$op\evidence\container-exit.txt"
Get-Content "$op\output\common_design_envelope.json" -Raw
```

All mount sources and evidence must be real absolute native paths beneath results,
not linked files/junctions. No tmpfs or source-tree writes. Dockerfile sets HOME,
TMPDIR/TMP/TEMP and XDG_CACHE_HOME to these persistent mounts. For POSIX use native
separators/quoting. Windows integration may add `--context desktop-linux` before
`run`/`build`. Missing image, engine, action or mounts is BLOCKED, not permission
to install software or invent a tool call.

Require actual exit 0, CDE completed/pass, DEFAULT violations 0 and unformatted
files 0. No waivers, rules/config overrides, style not_gating or disabled format
gating for closure. Optional diagnostic configurations remain available but are
not DEFAULT closure. Standalone `lint` and `format` cannot close the stage.
Return container exit, native subcheck codes, CDE status/verdict/error and proposals
separately. CDE references resolve under `$op\output`. Keep proposals separate;
never mutate inputs. Worker refuses nonempty output/work. Each retry gets a fresh
operation. Preserve hashes; adopted RTL changes require all three parent-routed gates.
Run packaged regressions in the same mount layout with
`python3 -B -m unittest discover -s /app/tests -p 'test_*.py' -v`.

## Review discipline

Lint is a review gate: zero violations passes, any violation fails. Waivers are
applied only via the caller-supplied `waiver_files`; rules are never silently
ignored. Verible is installed from the upstream static linux release (no Debian
package exists).

## Historical build maintenance

The Verible version is pinned in the Containerfile (`ARG VERIBLE_VER`) for
reproducible builds. Version upgrades are outside this backend-only migration.
Use the supervised staged Docker plan without overriding the pinned version:

```powershell
python agents-docker\shared\build_docker.py --check --run-id <run-id>
```

Latest tags: <https://github.com/chipsalliance/verible/releases>.
# Services qualification deployment

`services-deployment.json` pins the qualified Services image when deployed.
`tools/rtl-lint/Services.Dockerfile` retains the immutable original native engines
and overlays the current worker without software installation. Append
`services-instructions.md` to the source agent instructions. Jobs are capped at
2 CPU / 4Gi. `CDE_JSON=` in native logs reproduces the exact persisted envelope
even when failed Services jobs omit assets; completed/fail is not pass.
