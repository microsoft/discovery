---
asset_class: agent
canonical_name: RTL Design Agent
flow_stage: B - RTL Design and Verification
node_awareness: node-agnostic
tier: 1
nature: reasoning / orchestrated
required_tools:
- RTL Design Tool
required_skills:
- RTL Design Skill
- Verification Planning Skill
- Provenance Skill
supported_problems:
- synthesizable RTL authoring
- RTL hygiene / lint (inferred latches, undriven/multidriven nets)
- reset and clock-domain hygiene
- clock-domain-crossing enumeration for downstream signoff
emits: Common Design Envelope
---

# RTL Design Agent

## Overview

Node-agnostic RTL design agent. The agent authors synthesizable RTL and the tool verifies it in the same run, so authored RTL is never reported as good until it has elaborated and passed hygiene. Screens inferred latches, undriven and multiply-driven nets, and reset hygiene read structurally from the elaborated Yosys netlist (mixed async/sync style, mixed polarity, reset sampled as data, reset tied off). Node-agnostic (no PDK binding required).

## Architecture

A parameterized language-model prompt performs the assigned engineering work;
the bundled `rtl-design` container measures results and persists a Common Design Envelope.
The parent workflow owns dispatch, retries and downstream handoffs. The worker
reads immutable inputs from `/input` and writes evidence under `/output`.

## Prerequisites

Provide a Discovery-compatible model deployment, an authorized tool deployment
or local Docker/Podman engine, the input artifacts, and the explicit mount contract.
Container builds need network access to their declared upstream dependencies;
operation examples run without network access. No PDK binding is required.

## Configuration

Set `{{CHAT-MODEL}}` to the model deployment and `{{rtlDesignToolId}}` to the registered tool resource ID.
Use [params.schema.json](tools/rtl-design/params.schema.json) for operation parameters.
Mount `/input` read-only and provision fresh writable `/output`, `/workdir`,
`/tmp`, `/var/tmp`, `/home/worker`, `/run`, and `/dev/shm` directories.


**Purpose** — Author synthesizable, hygienic RTL from a specification or
verification plan, and prove it: no inferred latches, no undriven or
multiply-driven nets, and a coherent reset architecture.

**Responsibilities** — Author RTL; elaborate and confirm synthesizability; screen
for inferred latches, undriven and multiply-driven nets; check reset hygiene;
relate the RTL surface (ports, clocks, resets) to the shared verification plan.

**Supported problems** — Synthesizable RTL authoring with verification; RTL
hygiene/lint; reset hygiene; a starting clock/reset list for CDC signoff.

**Required tools** — RTL Design Tool (Yosys elaboration, hygiene and reset-hygiene
checks; emits a Common Design Envelope).

**Required skills** — RTL Design Skill, Verification Planning Skill, Provenance
Skill.

## Usage

Build the canonical image from the repository root with `docker build -t rtl-design:latest agents/chip-rtl-design/tools/rtl-design`.
Podman accepts the same build and run arguments. Only build with authorization;
never install an engine implicitly or silently reuse a stale image.

The declared `run` action reads `/input/params.json`; deployment must register
the tool and configure the mounts shown below. Merely importing this package
does not register an action or configure mounts. If unavailable, report BLOCKED
or use an explicitly authorized direct container invocation.

Independent PowerShell single-operation example, from project root:

```powershell
$op = Join-Path (Get-Location) ("results\rtl-design-" + [guid]::NewGuid().ToString('N'))
if (Test-Path $op) { throw "Operation already exists: $op" }
New-Item -ItemType Directory $op -ErrorAction Stop | Out-Null
'input','output','work','tmp','var-tmp','home','run','shm','evidence' | ForEach-Object {
    New-Item -ItemType Directory (Join-Path $op $_) -ErrorAction Stop | Out-Null
}
# Copy only required RTL into "$op\input"; example filename is dut.v, module dut.
# Reject linked paths and freeze input bytes before invocation.
'{"scenario":"check_authored","top":"dut","rtl_files":["/input/dut.v"]}' |
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
    rtl-design:latest python3 -B -u /app/run.py --params-file /input/params.json `
    1> "$op\evidence\stdout.log" 2> "$op\evidence\stderr.log"
$containerExit = $LASTEXITCODE
$containerExit | Set-Content "$op\evidence\container-exit.txt"
Get-Content "$op\output\common_design_envelope.json" -Raw
```

Use absolute native paths with no links/junctions; on POSIX adapt host separators
and shell quoting only. All inputs, writable mounts and logs stay under `results`;
do not use tmpfs. Dockerfile sets HOME, TMPDIR/TMP/TEMP and XDG_CACHE_HOME to these
mounts. Windows Docker Desktop integration may add `--context desktop-linux`
before `run`/`build`; do not bake it into source behavior. If engine/image/mounts
are unavailable report BLOCKED, never install software or invent a registered action.

Return the actual container exit, CDE status/verdict/error, native engine codes,
logs and formatting proposals separately. Exit 0 requires completed/pass, but
still inspect every required metric. CDE relative artifact references resolve
under `$op\output`, not the source folder. The worker refuses nonempty output/work
directories. Never reuse an operation; retain failed attempts. Run regressions in
this same mount layout with `python3 -B -m unittest discover -s /app -p 'test_*.py' -v`.

## Who authors, and who checks

The **agent** authors the RTL — that is its primary job, and real design work.
The **tool** is the bench instrument: it reports what the *elaborated* design
actually became, which is the only place several of these defects are visible at
all. An inferred latch is in the netlist, not in the source; the source only
contains the omission that caused it.

The tool deliberately does not generate RTL. An algorithm cannot write the RTL a
specification implies, and a template generator that pretended to would emit code
that elaborates cleanly and does the wrong thing — worse than emitting nothing.

### The authoring loop

1. **Interface first** — ports, widths, clock, reset polarity and style. Anything
   the request left open is either asked about or chosen *and stated*.
2. **Author** the module.
3. **Check** with `check_authored`.
4. **Repair** and re-check. Two or three passes are normal.
5. **Report** the RTL, the evidence, and the assumptions.

For file-supplied `rtl_files`, `check_authored` verifies formatting without changing
the read-only inputs. Final RTL stays at
`$op\input\<file.v>`; separate formatting proposals under
`$op\output\results` are not accepted RTL. Inline `rtl` is normalized
before checking and saved at `$op\output\results\<top>.authored.v`.
Freeze those final output bytes and rerun file-supplied checks before handoff.
Retain failed attempts; adopting a proposal requires a fresh design check,
DEFAULT lint/format and simulation on byte-identical RTL.

### Repair integrity

When the check fails, the fix belongs in the design — never in the measurement,
and never in the functionality that provoked it.

The cheapest way to clear an inferred latch is to delete the branch that caused
it, tie the signal off, or drop a case arm. Each makes the gate pass, and each
converts a *detected* hygiene defect into an *undetected* functional bug. If the
specification and the hygiene gate genuinely conflict, that is a finding to
report — not something to resolve by quietly shrinking what the module does.

A clean check means the design elaborates, infers no latch, has no undriven or
multiply-driven net, and has a coherent reset architecture. It says nothing about
whether the module does what was asked. Functional verification is a separate
gate.

## Reset hygiene: proven vs. advised

Reset defects are among the most expensive in a design. They are intermittent,
they survive most functional simulation — which typically applies one clean reset
at time zero — and they surface on silicon as a rare failure-to-start.

These are read from Yosys **cell types and parameters**, so they are facts about
the elaborated design rather than about spelling. They **gate**:

| Finding | Why it matters |
|---|---|
| one reset net used both async and sync | the two groups leave reset on different cycles, so there is no single reset boundary |
| one reset net used at both polarities | on assertion, half the design resets and half keeps running |
| a reset also sampled as data | defeats reset-tree treatment; a classic reset-domain-crossing bug |

These are **advisory**, because none is provable from structure alone:

- a net named `rst_n` used active-high (legal silicon, illegal communication)
- an async reset arriving straight from a port with no de-assertion
  synchronizer. Asserting asynchronously is fine; *releasing* asynchronously
  violates recovery/removal timing — but the synchronizer may legitimately live
  in a parent module, which is exactly why it does not gate
- a reset pin tied to a constant, so those flops never reset

A null `reset_hygiene_violations` means the netlist could not be examined. That
is not a clean reset result.

### Why structural and not regex

The `cdc_scan` path in this same tool infers clock domains by regex over raw
source text and then forms a cartesian product of clock names. Reset hygiene
deliberately does not repeat that method: when an elaborated netlist is
available, the netlist is the evidence.

**Inputs** — RTL (inline or file paths); top module; the shared verification plan
(optional) for surface tracing.

**Outputs** — Synthesizability verdict; hygiene findings (inferred-latch count,
undriven/multidriven nets, `check` problems); reset-hygiene findings separated
into gating and advisory; the clock/reset surface. All outputs conform to the
Common Design Envelope and Mandatory Output Fields.

**Handoff contract** — Emit a Common Design Envelope naming the RTL surface, the
hygiene and reset findings, and the clock/reset list so the Functional
Verification, CDC/RDC Signoff, and Logic Synthesis agents can consume it without
re-elaborating.

**Validation gates**

- Design elaborates without error.
- No inferred latches and no undriven/multiply-driven nets (or the run fails
  closed).
- `reset_hygiene_violations == 0`. A **null does not satisfy this gate** — resets
  that could not be examined return `pass_with_caveats`, never a flat `pass`,
  because "we could not check" is not "there is nothing wrong".
- Advisory findings are reported even when the gate is clean; a headline of "no
  issues" beside a non-empty advisory list is its own small lie.
- Authored RTL has been through `check_authored` before it is reported.
- Provenance present (node binding is `none`; node-agnostic).

**Known limits** — `cdc_scan` derives clock names by regex over the source text
and then lists every pair of names as a candidate crossing; it does not trace
dataflow, so it both over-reports (clocks that never interact) and under-reports
(gated, divided or mux-selected clocks). Treat it as a starting list for the
CDC/RDC signoff agent, which does the real enumeration — not as a crossing
analysis. Reset-hygiene analysis covers the module elaborated as top; a
synchronizer implemented in a parent is not visible from inside a submodule.

## Position in the flow

The front-end entry point: it produces hygienic, synthesizable RTL and the
clock/reset/crossing surface that every downstream agent depends on. It is
node-agnostic — technology mapping, corners, and node constants belong to the
Logic Synthesis and signoff agents, never to RTL hygiene.

## Node-Specific Notes

None. RTL hygiene is technology-independent; this agent introduces no node
constants, library cells, or corners.

## Tools

[rtl-design](tools/rtl-design/tool.yaml) exposes the fixed `run` action.
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
