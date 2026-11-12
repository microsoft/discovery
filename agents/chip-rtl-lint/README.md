# chip-rtl-lint — RTL Lint and Style Agent

## Overview

Node-agnostic RTL lint / style agent driven by Verible (verible-verilog-lint + verible-verilog-format), emitting a Common Design Envelope.

## Architecture

A parameterized language-model prompt performs the assigned engineering work;
the bundled `rtl-lint` container measures results and persists a Common Design Envelope.
The parent workflow owns dispatch, retries and downstream handoffs. The worker
reads immutable inputs from `/input` and writes evidence under `/output`.

## Prerequisites

Provide a Discovery-compatible model deployment, an authorized tool deployment
or local Docker/Podman engine, the input artifacts, and the explicit mount contract.
Container builds need network access to their declared upstream dependencies;
operation examples run without network access. No PDK binding is required.

## Configuration

Set `{{CHAT-MODEL}}` to the model deployment and `{{rtlLintToolId}}` to the registered tool resource ID.
Use [params.schema.json](tools/rtl-lint/params.schema.json) for operation parameters.
Mount `/input` read-only and provision fresh writable `/output`, `/workdir`,
`/tmp`, `/var/tmp`, `/home/worker`, `/run`, and `/dev/shm` directories.


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

## Usage

Build the canonical image from the repository root with `docker build -t rtl-lint:latest agents/chip-rtl-lint/tools/rtl-lint`.
Podman accepts the same build and run arguments. Only build with authorization;
never install an engine implicitly or silently reuse a stale image.

The declared `run` action reads `/input/params.json`; deployment must register
the tool and configure the mounts shown below. Merely importing this package
does not register an action or configure mounts. If unavailable, report BLOCKED
or use an explicitly authorized direct container invocation.

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

## Tools

[rtl-lint](tools/rtl-lint/tool.yaml) exposes the fixed `run` action.
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
