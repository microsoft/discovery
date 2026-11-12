# chip-functional-verification — Functional Verification Agent

## Overview

Node-agnostic functional-verification agent driven by Icarus Verilog, compiling and simulating RTL + testbench and emitting a Common Design Envelope with a pass/fail verdict.

## Architecture

A parameterized language-model prompt performs the assigned engineering work;
the bundled `functional-verification` container measures results and persists a Common Design Envelope.
The parent workflow owns dispatch, retries and downstream handoffs. The worker
reads immutable inputs from `/input` and writes evidence under `/output`.

## Prerequisites

Provide a Discovery-compatible model deployment, an authorized tool deployment
or local Docker/Podman engine, the input artifacts, and the explicit mount contract.
Container builds need network access to their declared upstream dependencies;
operation examples run without network access. No PDK binding is required.

## Configuration

Set `{{CHAT-MODEL}}` to the model deployment and `{{functionalVerificationToolId}}` to the registered tool resource ID.
Use [params.schema.json](tools/functional-verification/params.schema.json) for operation parameters.
Mount `/input` read-only and provision fresh writable `/output`, `/workdir`,
`/tmp`, `/var/tmp`, `/home/worker`, `/run`, and `/dev/shm` directories.


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

## Usage

Build the canonical image from the repository root with `docker build -t functional-verification:latest agents/chip-functional-verification/tools/functional-verification`.
Podman accepts the same build and run arguments. Only build with authorization;
never install an engine implicitly or silently reuse a stale image.

The declared `run` action reads `/input/params.json`; deployment must register
the tool and configure the mounts shown below. Merely importing this package
does not register an action or configure mounts. If unavailable, report BLOCKED
or use an explicitly authorized direct container invocation.

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

## Tools

[functional-verification](tools/functional-verification/tool.yaml) exposes the fixed `run` action.
It consumes `/input/params.json` and emits `/output/common_design_envelope.json`
with native engine diagnostics and relative artifact references. The bundled
`Dockerfile` is the canonical build definition; no alternate Containerfile is required.

## Known Limitations

A passing stage establishes only the contract described above, not whole-chip
correctness or signoff. Missing engines, mounts, metrics or evidence block a pass.
Model and tool resource IDs are deployment inputs, not executable local tool names.
Bookshelf grounding is optional and depends on explicitly attached sources.
Container builds and runtime engineering checks must be performed separately;
catalog format validation is not evidence that these engines executed.

## Contributing

See [CONTRIBUTING.md](https://github.com/microsoft/discovery/blob/main/CONTRIBUTING.md).
