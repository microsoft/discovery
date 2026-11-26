# chip-functional-verification — Functional Verification Agent

## Overview

Node-agnostic functional-verification agent driven by Icarus Verilog, compiling and simulating RTL + testbench and emitting a Common Design Envelope with a pass/fail verdict.

## Architecture

The prompt agent delegates to the bundled native worker. The canonical `tools/functional-verification/Dockerfile` builds this package independently; it does not require another chip-agent image, a shared-family build, or a private registry image. Existing worker source and native verdict gates are preserved. Legacy campaign and Services notes below describe historical runs, not validation of this migrated recipe.

Public build bases: the digest-pinned GHDL 5.1.1 GCC Ubuntu 24.04 and Verilator 5.036 images named in the Dockerfile. Base images must satisfy the target repository's current allowlist; a pinned digest does not itself establish policy approval.

## Prerequisites

Host Python is not required for the container runtime. Python and its build tools come from the base distribution; remaining Python dependencies are built from official GitHub archives pinned by full commit and SHA256 in [the source lock](tools/functional-verification/python_sources.lock.json). Installation disables package indexes and build isolation, then runs `pip check`; it does not contact the PyPI files host or disable TLS verification. Python 3.12 and cocotb-coverage 2.0 replace the prior forced cocotb 2.x/coverage-extension 1.x mismatch. The unused mandatory sfpy pin was removed: no bundled worker scenario imports it, and arbitrary user reference-model packages are not an implicit runtime guarantee. An optional [approved source cache](tools/functional-verification/dependency-sources/README.md) supports Python-source installation without GitHub access. OS package and base-image access are still required.

Docker with Linux containers, network access to the named public base registries and dependency sources, and the inputs required by the scenario. Supply PDK models, rule decks, libraries and user-design files separately with appropriate licenses; these are not embedded in this package. Keep builds and native probes sequential. Retain at least 15 GB free on the host before starting any build.

## Tools

`functional-verification` is defined in [tool.yaml](tools/functional-verification/tool.yaml). Its Docker build context is `tools/functional-verification/`; required runtime executable probes are included in the Dockerfile and fail the build when a dependency is missing.

## Configuration

The distribution supplies `ccache`, required by the copied official Verilator make configuration. The [toolchain probe](tools/functional-verification/verify_simulator_toolchain.py) compiles real timed RTL and executes four self-checking AND-gate vectors during the image build; version and import probes alone do not establish simulator build capability.

Use the action input schema and the scenario contract in `agent.yaml`. Mount design inputs and parameter files read-only at `/input`, with fresh writable `/output` and `/workdir` directories. File-based actions consume `/input/params.json`; actions declaring `params_json` retain their existing JSON argument contract. Read-only-root deployments additionally need the writable mounts described in the existing worker notes. Tool resource settings are inherited from the package, not newly measured budgets. The registry placeholder and tool ID are resolved by the catalog integration; no resource has been deployed by this migration.

## Usage

From this agent directory, build its own context:

```sh
docker build --file tools/functional-verification/Dockerfile --tag chip-functional-verification:local tools/functional-verification
```

After a successful build, run the retained scenario-specific smoke and negative-control fixtures with mounted input/output directories. Inspect the native process exit and persisted Common Design Envelope together; a successful container launch is not a passing engineering result.

## Known Limitations

The migrated Dockerfile was built and exercised in the local bounded-smoke campaign. This is not full engineering signoff: the campaign retained acceptance-blocked results for logic synthesis and the historical PPA DSE workload. Rebuild and replay in the target environment before relying on a result. Historical image digests, smoke results and Services receipts are not substitutes for verification of the current bytes. The local historical dispatcher intentionally rejects source drift until an authorized rebuilt-image baseline is recorded. Missing caller intent, PDK collateral, acceptance evidence or toolchain capabilities must remain visible and cannot be replaced with invented defaults. Original long descriptions, domain keywords, action examples and removed schema-unsupported metadata are retained in [catalog-details.json](catalog-details.json); worker-side parameter validation remains unchanged.

## Contributing

Follow the target repository's [contribution guide](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md) and agent-authoring requirements. Changes to base-image policy need separate maintainer review. Never edit generated registry entries.

## Retained worker and historical campaign notes


Node-agnostic **functional-verification** agent. Compiles RTL + a testbench with
**Icarus Verilog** (`iverilog`), runs the compiled object with `vvp`, and reports
a fail-closed verdict with a required nonempty VCD for Icarus self-check success.

- **Engine:** Icarus Verilog (`iverilog -g<std> -o sim.vvp ...` + `vvp sim.vvp`)
- **Node awareness:** node-agnostic (no PDK binding).
- **Output:** Common Design Envelope (`/output/common_design_envelope.json`); any dumped
  VCD is preserved under `results/`.

## Scenario

| Scenario | Purpose |
|---|---|
| `run_sim` | Compile RTL + testbench, run the event simulation, report pass/fail + VCD. |

## Ordinary local execution

This OpenSTA-style package includes `agent.yaml`, `metadata.yaml`, README and the
complete `tools/functional-verification` build context. It has no shared-code or
host-launcher dependency. Discovery parent owns dispatch and handoffs.

Use `.github/skills/discovery-add-agents/SKILL.md` Steps 5/6 with local
`$srcRoot=agents-docker` and exactly the three selected roles, not an upstream
refresh that would discard these edits. Copy only to an absent destination:

```powershell
$name = 'chip-functional-verification'
$dst = Join-Path (Get-Location) "discovery_catalog\$name"
if (Test-Path $dst) { throw "Destination exists: $dst" }
New-Item -ItemType Directory -Force discovery_catalog | Out-Null
Copy-Item -Recurse "agents-docker\$name" $dst
# Run the skill's Step 6 with $selected=@($name).
```

Local copy/companion generation supplies lazy bootstrap, **not action registration
or mounts**. YAML IDs do not become callable Copilot tools. Use `run` only if
actually registered with the mounts below; otherwise invoke one container directly.
The fixed action reads `/input/params.json` using the contract in
`tools/functional-verification/params.schema.json`, never shell-interpolated JSON.

Importer image: **`functional-verification:latest`**. Inspect first; only if absent:
`docker build -t functional-verification:latest agents-docker\chip-functional-verification\tools\functional-verification`.
After import use `discovery_catalog\chip-functional-verification\tools\functional-verification`.
Podman uses the same arguments. Engine installation, readiness and context are
integration responsibilities. Existing tags are not automatically refreshed by
source edits; explicitly select a source-current image.

PowerShell single-operation example, from project root:

```powershell
$op = Join-Path (Get-Location) ("results\functional-verification-" + [guid]::NewGuid().ToString('N'))
if (Test-Path $op) { throw "Operation already exists: $op" }
New-Item -ItemType Directory $op -ErrorAction Stop | Out-Null
'input','output','work','tmp','var-tmp','home','run','shm','evidence' | ForEach-Object {
    New-Item -ItemType Directory (Join-Path $op $_) -ErrorAction Stop | Out-Null
}
# Copy only frozen dut.v and independent tb_dut.v (module tb) into "$op\input".
'{"scenario":"run_sim","top":"tb","rtl_files":["/input/dut.v"],"testbench_files":["/input/tb_dut.v"],"generation":"2012","wave_format":"vcd"}' |
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
    functional-verification:latest python3 -B -u /app/run.py --params-file /input/params.json `
    1> "$op\evidence\stdout.log" 2> "$op\evidence\stderr.log"
$containerExit = $LASTEXITCODE
$containerExit | Set-Content "$op\evidence\container-exit.txt"
Get-Content "$op\output\common_design_envelope.json" -Raw
```

All mount sources and evidence are real, absolute host-native paths beneath results.
Reject links/junctions, do not use tmpfs, and never write runtime data to the source
tree. Dockerfile sets HOME, TMPDIR/TMP/TEMP and XDG_CACHE_HOME to the persistent
mounts. For POSIX adapt host separators/quoting. Windows integration may add
`--context desktop-linux` before `run`/`build`. Unavailable engine/image/action/mounts
is BLOCKED; never install software or invent a tool call.

Return actual container exit, native compile/sim codes, CDE status/verdict/error and
waveform separately. CDE references resolve under `$op\output`. Worker refuses
nonempty output/work; retain failures and use fresh operation paths for retries.
Preserve RTL/TB hashes and do not modify DUT. Run packaged regressions in this
mount layout using `python3 -B -m unittest discover -s /app -p 'test_*.py' -v`.
GHDL/cocotb/GLS paths are retained but are not substitutes for the Icarus contract.

## Verdict discipline

Icarus success requires exactly one `COMPARISONS=n MISMATCHES=m` summary with
n > 0 and m = 0, an exact standalone `TEST PASSED`, no error/failure/fatal markers,
native compile/sim exits 0 and a nonempty VCD. Generic success prose, missing or
incorrect markers, zero comparisons and missing waveform all fail closed. A pass
marker never overrides an error. Read these measured fields in the CDE; absent
metrics do not pass. This does not establish timing or CDC signoff.
# Services qualification deployment

`services-deployment.json` pins the qualified Services image when deployed.
`tools/functional-verification/Services.Dockerfile` overlays current source on the
immutable original engine image without software installation. Append
`services-instructions.md` to source agent instructions. Jobs are capped at
2 CPU / 4Gi. `CDE_JSON=` reproduces the exact persisted envelope for failed
Services jobs without output assets. An orchestration success never overrides a
failed native simulation or missing independent self-check evidence.
