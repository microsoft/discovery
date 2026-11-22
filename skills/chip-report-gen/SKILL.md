---
name: chip-report-gen
description: "Use automatically before the final handoff for chip, ASIC, FPGA, RTL or silicon design, verification and implementation work: authoring RTL, lint, formatting, simulation, testbenches, waveforms, debugging, formal checks, synthesis, timing, PPA, physical design and signoff. Applies to single-stage and multi-agent runs, including failed or blocked attempts, even when the user asks only to implement or verify a design or save a short results summary and never mentions a report or HTML. Create an evidence-grounded offline HTML report as the chip/RTL final report alongside the requested summary, including a visual agent invocation sequence with recorded reasons, outcomes and retries. Reporting only: never dispatch agents or rerun engineering. Skip planning-only questions and explicit reporting opt-outs."
license: MIT
compatibility: Requires Python 3.10+; standard library only; no network access required.
---

# Evidence-first HTML reporting

Use the bundled deterministic renderer; do not substitute a prose-only promise
of plots. This skill reads existing evidence and creates one offline HTML file.
It does not orchestrate a workflow, activate agents, dispatch specialists, run
containers, install dependencies, serve HTTP, or rerun engineering.

## Automatic invocation and completion gate

The parent assistant must load and use this skill before its final handoff
after performing chip design, verification or implementation work that produces
artifacts, native results or a recorded failed/blocked attempt. Do not wait for
the user to request "report", "HTML", "chip-report-gen" or "results summary".
The discovery description above is deliberately broad so this requirement is
visible before the skill body is loaded.

This includes RTL authoring, lint and canonical formatting, independent
testbenches and simulation, waveform analysis, verification debugging,
assertions and formal checks, synthesis, timing and constraints, PPA analysis,
analog/SPICE work, physical implementation, DRC/LVS and signoff. Apply it to
single-agent/single-stage work as well as a complete multi-agent workflow.
Failed or blocked engineering is reportable evidence, not a reason to skip
the reporting step.

- "Implement the design in knowledge/design-spec.md" triggers reporting after
  the requested implementation/checks.
- "Run these three agents in order and save RTL, testbench, VCD and a short
  results summary" triggers reporting after the final requested gate.
- "Run default lint", "simulate this RTL", "debug this verification failure"
  and "check timing/PPA" trigger reporting after the requested work.
- Pure explanations, planning, agent/skill configuration edits and unrelated
  software work do not trigger a chip report by themselves. Honor explicit
  instructions such as "no report", "no HTML", "Markdown only" or "only return
  the RTL"; produce only the permitted deliverables.

A request for a short summary is not a reporting opt-out. A specified ordered
agent list is not a reason to omit this skill: reporting is a parent-owned
completion step, not another engineering agent or gate. A prohibition on
scientific reasoning agents does not prohibit this reporting-only skill.
Do not invoke such agents, add engineering stages or change the requested
agent order to generate a report.

Run reporting once at the final handoff of the requested workflow, not after
every intermediate stage. Report only the current requested run. Reuse an
already generated, verified report for unchanged evidence rather than
creating redundant reports.

Before completing the task:

1. Preserve the requested source artifacts and short results summary. Prepare
   the renderer's `results.json`/`results.md` evidence contract from actual
   outputs when the run does not already have it, using the schema below.
   Never invent invocations, exits, hashes, timestamps or measured results.
   Preserve the complete agent dispatch history, including blocked initial
   attempts and all repair/recheck invocations, in `artifacts.dispatch_record`.
   For each entry record the agent, why it ran, its actual outcome and explicit
   status. The renderer creates a visual numbered, connected sequence with
   status colors and per-agent counts, without Mermaid or external libraries.
   Do not substitute only the final passing stages for the invocation history.
   Missing reasons/outcomes remain "not recorded"; never reconstruct them from
   native gate results. See the dispatch schema in references/usage.txt.
2. Execute the bundled renderer on that run. Use the user's output destination
   and keep reporting artifacts inside any user-required run directory. If no
   destination was specified, follow the default destination rules below.
3. Check the real renderer exit, console evidence issues and nonempty HTML;
   verify local artifact links and inspect the report in an available browser.
   Rendering success is not engineering PASS.
4. Link both the HTML and requested summary in the final response, retaining
   separate links to requested RTL, testbench, waveform or other native files.
   State any failed gate, rendering issue or unverified browser inspection.

For design-only or non-simulation work, do not add a simulation just to obtain
a VCD. Report the available evidence and the absence of a recorded waveform.
Missing or unsupported evidence must stay visible; do not fabricate it, weaken
validation or suppress an exit 2 to make automatic reporting look successful.
If rendering is blocked, retain the available summary and report the actual
blocker rather than silently omitting the reporting step.

## Inputs and destination

1. Resolve the user's existing run directory. Inspect its `results.json`,
   `results.md`, artifacts, attempt audits and native envelopes. Do not select
   an arbitrary successful run when a particular run was requested.
   For native per-stage runs without smoke-test audits, require explicit
   `stages[].execution_evidence` links to existing invocation, exit and RTL
   files. Follow the [schema contract](references/usage.txt); never fabricate
   an audit to satisfy the renderer. An `execution_mode: "ordered"` claim
   also requires native worker timestamps and identical measured RTL hashes.
2. Use an explicit output file exactly as requested. If the user specifies an
   output directory, append `report.html`. If the user explicitly asks for a
   report alongside the run, use `<run-dir>\report.html`. Otherwise honor the
   session's output convention: in this project create
  `results\chip-report-gen-<UTC timestamp>-<unique id>\report.html`. The renderer's
   no-output default implements this project convention for a run under
   `results`; for other locations it requires an explicit destination. Never
   overwrite existing reports, skills or evidence.
3. Resolve the actual skill directory and execute from the project root using
   the installed Python, with quoted paths. Replace the placeholders below:

```powershell
python -B '<skill-directory>\scripts\render_report.py' `
  --run-dir 'results\<existing-run-id>'
```

An explicit destination is also supported:

```powershell
python -B '<skill-directory>\scripts\render_report.py' `
  --run-dir '<existing run>' --output '<new directory>\report.html'
```

`--vcd <run-relative path>` selects an alternate trace. `--signals` accepts
comma-separated **exact scoped names** (up to 12) to replace automatic signal
selection. Run `--help` for resource limits. No network or third-party packages
are needed. See [renderer contract](references/usage.txt).

## Interpretation and handoff

The report separates the source-reported native verdict, evidence review, and
agent activation. `completed`, missing, null and unknown are not PASS. A native
FAIL/BLOCKED or contradictory evidence remains visible even if a summary says
PASS. Rendering successfully never certifies the engineering.
Keep `workflow_status`, stage `executor` and any parent-recorded
`artifacts.dispatch_record` distinct from native verdicts. If a named agent
was blocked and the parent ran its native contract, report that fallback
honestly; a passing tool result is not successful named-agent execution.

Use measured coverage counters, not invented percentages or timing signoff.
Elapsed charts use only explicitly recorded native runtime fields and identify
their basis. Original Markdown and simulation logs are escaped text, not trusted
HTML. Artifact/source links stay local and relative to the generated HTML.

Waveforms use actual VCD timescale and transitions, scalar/bus values and X/Z.
Representative windows identify observed signal patterns, not coverage proofs.
Signal selection, parser limitations, resource refusal and dense-pixel events
are disclosed. Keep the native VCD link. Missing/invalid traces get an explicit
fallback, not fabricated waveforms. Exit 2 means the HTML was written with
evidence issues; exit 1 means rendering itself failed. Read the console JSON.

Return the generated HTML link, material evidence issues, and any limitations.
If browser tooling is available inspect the rendered file; otherwise say visual
rendering is unverified. Skill file placement/frontmatter is not proof of
runtime activation: use an actually available catalog/skill facility to check
`chip-report-gen`; if none is exposed, report discovery/activation as unverified.
Do not guess registration APIs or modify agent definitions.

Use the project renderer path shown above when validating project source
changes. A cached runtime-installed copy may still contain older code;
do not overwrite it or assume it automatically follows project edits.

Example end-to-end user prompt:

> Use chip-report-gen to create the final HTML report for
> results\<existing-run-id>. Summarize the existing chip/RTL
> evidence and include actual simulation waveforms. Save it in a fresh
> results\<unique-run-id>\report.html; do not rerun engineering.
