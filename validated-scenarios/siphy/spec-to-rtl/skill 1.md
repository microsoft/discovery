---
name: quickstart-siphy-spec2rtl-1
description: "Guided, interactive Quick Start runner. Executes the quickstart described by a quickstart template document and the Quickstart Profile section of this skill (currently: CoreSPI specification-to-verified-RTL, knowledge/quickstart-template.md). Starts prerequisite/setup checks immediately, asks the user before any installation or consequential decision (always offering a recommended answer, at least one alternative and a free-form option), then asks whether to run the rest autonomously end-to-end or as a step-by-step walk-through, explains the purpose and expected outcome of every phase by default, runs the profile's fixed agent sequence with validation between steps, and finishes with a results summary and report. All generated files go under results/<unique-run-id>/. USE FOR: 'run the quickstart', 'run the CoreSPI quickstart', 'spec to RTL quickstart', 'siphy spec2rtl'. DO NOT USE FOR: editing the quickstart template itself."
argument-hint: "Optional: run id, run mode ('autonomous end-to-end' or 'walk-through'), or answers to setup questions (for example 'keep the existing protected file')."
user-invocable: true
---

# Quick Start Runner (Sequential Pipeline)

## How to adapt this skill to another quickstart

Everything above [Quickstart Profile](#quickstart-profile) is generic and must
not name a specific design, vendor, agent or file. To run a different
quickstart, copy this skill folder, give it a new `name`, update the
`description` and **replace only the Quickstart Profile section**. Every
quickstart provides a template document (same structure as
`knowledge/quickstart-template.md`); the profile points to it.

Generic sections refer to profile fields as `QP.<field>` (for example
`QP.steps`, `QP.images`). Placeholders such as `<run-id>` and
`<rtl_sha256>` are substituted at run time.

## Purpose

This skill replaces manually following a quickstart template document
(`QP.template`). It executes a fixed sequential pipeline (`QP.steps`). It
delegates each step to the named agent via the runtime's sub-agent mechanism
(`runSubagent` or the equivalent task tool), validates that result, and
passes only validated outputs to the next step. Before Step 1 it runs an
**interactive setup** that checks prerequisites and asks the user to resolve
anything unclear or missing. The run's objective is `QP.goal`.

**The template is authoritative.** Read `QP.template` at the start of every
run. Its fixed prompt (template section "Fixed prompt + matching output") is
the governing instruction; this skill implements that prompt and never rewords
or weakens it. Use the template's prerequisites, setup, expected-runtime and
troubleshooting sections for setup checks, briefings and failure guidance. If
the template and the profile disagree, pause and ask the user which one
governs (recommend the template) and record the answer. PASS means only what
`QP.verdict_rule` says; never claim more than `QP.limitations` allow.

**User experience flow**

1. **Setup starts right away.** On invocation, read `QP.template`, print the
   setup card and immediately begin the read-only prerequisite checks
   (P1-P9). Do not ask for permission to start checking; ask only the
   questions setup requires. Every setup message carries the setup banner
   (see [Message Formatting](#message-formatting)) so the user can tell
   one-time environment preparation apart from the workflow itself.
2. **Choose the run mode next.** As soon as setup is resolved, ask P10: run
   the rest of the quickstart **autonomous end-to-end** or as a
   **walk-through** (see [Run Modes](#run-modes)).
3. **Every phase is explained by default.** Before each phase (each step in
   `QP.steps`, any repair-cycle repeat, and final validation and reporting),
   show the phase card without the user having to ask for it; in
   walk-through mode the card and the checkpoint choices are presented
   together in one prompt. After each phase print a short debrief of what
   actually happened.

**Deterministic execution contract**

- Execute steps strictly in ascending numeric order.
- Run one agent at a time and wait for completion.
- Never substitute, rediscover, or dynamically select agents at runtime.
- Never skip, reorder, parallelize, or append steps.
- Validate before handoff.
- Retry a failed step at most once, using the same agent and inputs plus the
  failed checks. The only exception is the profile's repair cycle
  (`QP.repair_cycle`), bounded by its maximum cycle count.
- Stop on unresolved failure and expose the failed checks.
- Produce the final deliverable only after all final checks pass.
- Explain every phase by default before it runs and debrief after it; in
  walk-through mode, also wait for the user's go-ahead before each phase.
  Run mode never changes the steps, agents, inputs or validation.

## Run Modes

Selected at P10, recorded in `preflight.json` as `run_mode`, and switchable
at any walk-through checkpoint.

| Mode | Behavior | When the user is asked something |
|---|---|---|
| **Autonomous end-to-end** (recommended) | Runs every step, final validation and reporting without pausing. Phase cards and debriefs are still printed. | Only for consequential decisions, contradictions or failures (Execution Rule 11). |
| **Walk-through** | Same pipeline, but pauses at a checkpoint before each phase after setup. | At every checkpoint, plus everything in autonomous end-to-end mode. |

**Walk-through checkpoint.** Present the phase card and the choices together
in a single `ask_user` call: the question text is the phase card followed by
a blank line and `❓ Ready to run <phase name>?` (plain text; see
[Message Formatting](#message-formatting)); the choices are
`Run this step (Recommended)`,
`Switch to autonomous end-to-end for the remaining steps`, `Stop here`
(free-form is supplied by the UI; a free-form question is answered and the
checkpoint is asked again). Do not offer an "explain" choice and do not print
the card in a separate turn before asking. Choosing "Stop" ends the run with
the Failure Report marked `STOPPED BY USER` and links to the validated
outputs so far. Pausing never alters what the step does.

In autonomous end-to-end mode, print the same phase card as a message and
proceed immediately.

## Message Formatting

User-facing text appears in two places that render differently. Use the
right style for each. No hashes, command lines, parameter lists or internal
rule numbers; name only the main output files. Keep each line to about 15
words.

| Where | Renders Markdown? | Style |
|---|---|---|
| Chat messages (setup card in autonomous mode, phase cards in autonomous mode, debriefs, final response, failure report) | Yes | Markdown patterns below (bold, links, tables). |
| `ask_user` question text (every setup question, walk-through checkpoint, runtime decision) | **No** | **Plain text only.** |

**Plain-text rules for `ask_user`.** The question box shows characters
literally. Never use `**`, `__`, backticks, `>` quotes, `#` headings,
Markdown links or `- ` bullets in question text. Start every line at
column 0 (no leading spaces or tabs, no indented continuation lines). Use
emoji as the visual anchor at the start of a line, a single blank line
between blocks, and `:` after labels. Put file names in plain text or
quotes. Keep choice labels short (about 12 words or fewer); put detail in
the question text.

**1. Setup banner (setup only).** Every setup message and setup question
(the setup card, P1-P10 questions and the setup summary) starts with this
banner line, followed by a blank line. Never use it after setup.

```text
🛠️ ONE-TIME SETUP · Preparing your environment. The Discovery workflow starts right after.
```

In a chat message the same banner may be rendered as
`> 🛠️ **One-time setup** · Preparing your environment. The Discovery workflow starts right after.`

**2. Setup question (`ask_user`, plain text).** Banner, one sentence of
context, then the question on its own line.

```text
🛠️ ONE-TIME SETUP · Preparing your environment. The Discovery workflow starts right after.

📄 knowledge/<file> already exists from an earlier run.

❓ What should Step <k> do with it?
```

**3. Phase card (before each step and the final phase).** Take the content
from the phase's `Briefing`. The **Discovery** line names the Discovery
app capability the phase exercises (for example a specialist agent from
the Agents catalog, a connected MCP tool, a Bookshelf, a skill, or a
containerized engine run by an agent). Omit Heads-up when nothing is
notable. Add a `Repair cycle: k of <max> · <one-line reason>` line only for a
repair-cycle repeat.

In `ask_user` (walk-through checkpoint), plain text:

```text
▶ STEP <k> OF <N> · <PHASE NAME>

🎯 Why: <what this phase achieves for the user>
🤖 Who: <agent or "I", and the main tool>
🧩 Discovery: <Discovery capability used in this phase>
📦 You'll get: <1-3 main outputs>
✅ Done when: <the key pass condition>
⏱️ Heads-up: <duration and any question or known risk>

❓ Ready to run <phase name>?
```

In chat (autonomous mode), Markdown:

```markdown
**▶ Step <k> of <N> · <phase name>**

- 🎯 **Why:** <...>
- 🤖 **Who:** <...>
- 🧩 **Discovery:** <...>
- 📦 **You'll get:** <...>
- ✅ **Done when:** <...>
- ⏱️ **Heads-up:** <...>
```

The final phase uses the title `Final check & report`; the setup card uses
the banner, then `Setup` and the same lines.

**4. Debrief (chat, after each phase).** At most 3 lines: verdict with one
or two key numbers, links to main outputs, and any decision recorded.
Verdicts come from validated evidence, never from the agent's prose alone.

```markdown
**✅ Step <k> · PASS** — <one or two key numbers>
📄 [<main output>](<workspace-relative link>) · [<output>](<link>)
📝 <decision recorded, if any>
```

Use ✅ PASS, ❌ FAIL, ⛔ BLOCKED or ⏹️ STOPPED. Put the next phase in its own
card rather than the debrief. Deeper detail (exact checks, delegate text,
evidence paths) is given only if the user asks.

**5. Setup summary (`ask_user`, plain text)** inside the run-mode question
(P10):

```text
🛠️ ONE-TIME SETUP · Preparing your environment. The Discovery workflow starts right after.

✅ Setup complete: Agents ✅ · Containers ✅ · Python ✅ · Connected tools ✅ · Bookshelf ✅
📝 Decisions: <decisions, separated by " · ">

🚀 Autonomous end-to-end: runs every step and the report; stops only for decisions or failures.
👣 Walk-through: explains each step and waits for your go-ahead.

❓ How do you want to run the rest of the quickstart?
```

**6. Runtime decision (`ask_user`, plain text, no banner).**

```text
⚠️ DECISION NEEDED · <where in the run>

<one or two short lines of context, each starting with an emoji or plain text>

❓ <question>
```

Duration guidance must be honest. Use only the template's expected-runtime
section: quote values labelled **Measured**, label older or
different-profile values as historical, and otherwise say "a few minutes" or
"can take tens of minutes". Never invent a benchmark.

## Phase 1: Setup and prerequisites (parent, starts immediately)

**Briefing (setup):** Why: make sure this machine can run everything before
work starts. Who: I check agents, containers, Python and connected tools.
Discovery: Agents catalog, connected MCP tools and Bookshelves.
You'll get: `preflight.json`. Done when: every check passes or you've
decided how to handle it. Heads-up: a few minutes; nothing is installed or
overwritten without your answer.

Print the setup card (with the setup banner), then immediately start P1
without waiting for input. Run every check below in order. **Never install
software, build images, change connections, or overwrite files without an
explicit user answer.** Ask with the `ask_user` tool, one question at a
time, formatted as a plain-text setup question (banner, one sentence of
context, question line; no Markdown markup). Every question MUST provide:

1. the recommended answer first, labeled `(Recommended)`;
2. at least one alternative answer;
3. the free-form option (the UI supplies it automatically; if the runtime has
   no `ask_user` tool, or the `ask_user` call returns an error, print the
   same formatted question with numbered choices plus "or reply with your
   own answer", end the turn and wait; never assume an answer).

Skip a check that does not apply to the profile (for example, P3-P4 when
`QP.images` is empty). Skip a question when its check passes or the user
already answered it in the invocation arguments. Record every question, answer
and check result in `results/<run-id>/preflight.json`.

| # | Check (actual command or inspection) | Ask only when | Question and choices |
|---|---|---|---|
| P1 | Allocate `results/<run-id>/` using `QP.run_id_format`; refuse an existing path. | User supplied a run id that already exists or is not filesystem-safe. | "Which run id should I use?" — `Generate a new unique id (Recommended)`, `Use <user-id>-<suffix>`. |
| P2 | Every agent in `QP.agents` is listed by the runtime agent catalog (file presence alone is insufficient), and every skill in `QP.skills` is listed. | Any is missing or not invocable. | "Agent/skill X is not available. How should I proceed?" — `Stop so you can install it, then start a new chat (Recommended)`, `Copy it from the template's bundle without overwriting, then stop`. |
| P3 | Container engine responds (`docker info`; on Windows `docker context show` is `desktop-linux`) or `podman info` responds. | No responsive engine. | "No container engine is running. What should I do?" — `I'll start it; wait and recheck (Recommended)`, `Install Docker Desktop with winget (you confirm prompts)`, `Use Podman instead`, `Stop`. |
| P4 | `image inspect` for every image in `QP.images`; record image ids. | Any image missing. | "Image X is missing. Build it locally from its build context in `QP.images`?" — `Build missing images only (Recommended)`, `Stop; I'll build them myself`. Never push, and never pull anything beyond the Dockerfile's base images. |
| P5 | A full Python ≥ 3.10 (not the Windows Store `python.exe` alias; exit 9009 means alias) for the HTML report. | Not found. | "Python ≥ 3.10 is needed for the HTML report. Install it?" — `Install Python 3.13 with winget (Recommended)`, `Use an interpreter path I'll provide`, `Continue without the HTML report (run reported as partial)`. |
| P6 | Each entry in `QP.external_tools` is exposed and callable by its named agent; run the entry's probe through that agent and record tool name, outcome and timestamp. | Tool not exposed or probe fails. Report the actual error or "tool unavailable; no connection attempted". | "<agent> cannot use <tool>. How should I proceed?" — `Stop so you can connect it in Discovery, then start a new chat (Recommended)`, `<the entry's documented fallback> (tool-use check recorded as NOT met)`. |
| P7 | For each file in `QP.protected_files` that already exists, record its SHA-256. | It exists. | "<file> already exists. What should <step> do?" — the entry's choices, recommended first (typically keep-and-append vs replace-after-backup to `results/<run-id>/backup/`). |
| P8 | Each scope decision in `QP.scope_decisions`. | Its condition holds. | The entry's question and choices, recommended first. |
| P9 | Bookshelf grounding (`QP.bookshelf`). Mode `always`: verify the named shelf is listed and indexed (for example via `discovery.bookshelf.listShelves`) and record it; no question. Mode `optional`: ask once. Mode `none`: skip. Consultation must always be evidenced in files, never assumed. | Mode `always` and the shelf is missing or not indexed; or mode `optional`. | Missing: "The <shelf> Bookshelf isn't available. How should I proceed?" — `Stop so you can create or index it, then rerun (Recommended)`, `Continue without it (Bookshelf use recorded as NOT met)`. Optional: "Should the agents consult a Bookshelf?" — the profile's choices, recommended first. |
| P10 | Run mode, as the setup summary (Message Formatting pattern 5). | Always (skip only if the invocation already named a mode). | "How do you want to run the rest of the quickstart?" — `Autonomous end-to-end (Recommended)`, `Walk-through`, `Change a setup answer first`, `Stop`. |

After P10, record `run_mode` and continue to Step 1 without the setup
banner. In walk-through mode, ask the Step 1 checkpoint question; in
autonomous end-to-end mode, print the Step 1 card and proceed.

Anything else unclear during the run (for example, a contradictory requirement
reported by an agent) is resolved the same way, but without the setup
banner: pause, ask with a recommended answer plus alternatives, record the
answer, then continue. Do not invent missing requirements.

## Execution Rules

1. Complete setup, including the P10 run mode, and record `preflight.json`
   first.
2. Execute `QP.steps` strictly in ascending numeric order. Before each phase
   show its card; in walk-through mode present the card and checkpoint
   choices together and act on the answer; after each phase print its
   debrief.
3. Invoke exactly one sub-agent at a time, synchronously, and wait for it to
   finish. Each specialist runs its own tools or container operations per its
   agent definition; the parent never substitutes direct tool or container
   execution for a named agent. If a named agent cannot be invoked, stop as
   BLOCKED with the exact limitation.
4. Use only the agent named by the current step. Do not substitute agents,
   including variants listed in `QP.forbidden_substitutes`.
5. Pass only the declared runtime inputs, setup answers and validated
   `Consumes` outputs. Substitute the actual `<run-id>` and hashes in every
   delegate prompt, and append the relevant setup answers (including P9).
6. Every generated file, operation directory, mount, log and evidence item
   stays under `results/<run-id>/`; the only exceptions are the files listed
   in `QP.protected_files`. Nothing under `sessions/`, host temp or other
   shared folders.
7. Validate each result by reading the actual files and native evidence
   (for example, Common Design Envelopes), not the agent's prose alone.
8. On validation failure of a step outside the repair cycle, retry that step
   once with the failed checks appended. If the retry fails, stop.
9. **Repair cycle (`QP.repair_cycle`, fixed maximum):** when a step in the
   cycle fails for a reason the profile attributes to the primary artifact,
   start a new cycle at the cycle's first step with the exact failing
   diagnostics appended, then rerun every later step in the cycle on the new
   artifact. Defects the profile attributes to a step's own outputs (for
   example, a testbench) are corrected inside that step and do not start a
   new cycle. After the last allowed cycle fails, stop.
10. If the primary artifact (`QP.repair_cycle.artifact`) changes for any
    reason, every step in the cycle must pass again on the identical final
    artifact hash.
11. Do not reinterpret the plan or add steps during execution. Questions to
    the user are allowed only during setup, at walk-through checkpoints, and
    (in either mode) when an agent reports a contradiction or a consequential
    decision the recorded answers do not cover, such as a conflict between
    the profile and a generated contract, or a repair that would change a
    recorded decision. Record each runtime question and answer under
    `runtime_decisions` in `preflight.json`.
12. Return the final result only after all final validation checks pass;
    otherwise return the Failure Report.

## Final Validation and Report

**Briefing (final phase):** Why: confirm every check passed on the same final
result and package the evidence. Who: I check hashes and run the report
skill. Discovery: the report-gen skill renders an offline HTML report.
You'll get: `results.md` and an HTML report. Done when: everything
matches and the report renders. Heads-up: a few minutes.

- Every step validated, in order; the final runs of all repair-cycle steps
  record the same artifact SHA-256 (recompute it from the file).
- Every file in `QP.deliverables` exists and is nonempty.
- No file generated by this run exists under `sessions/`.
- Write `results/<run-id>/dispatch.json` recording every agent invocation in
  order (agent, reason, outcome, status), including failed or blocked attempts
  and repair-cycle repeats.
- Write `results/<run-id>/results.md`: overall verdict per
  `QP.verdict_rule` (otherwise the actual failure), gate table, key counts,
  artifact hash, setup and runtime decisions, external-tool-use outcomes,
  coverage omissions, limitations and links.
- Load `QP.report_skill` and render its report for `results/<run-id>/`
  following that skill's contract. Apply `QP.report_notes`. Never overwrite a
  previous report or suppress issues. Check local links.
- Final response (short), formatted as:

  ```markdown
  **✅ PASS** — <key counts>

  | Output | Link |
  |---|---|
  | <each entry in QP.final_links> | [<file>](<workspace-relative link>) |

  ⚠️ **Limitations:** <one line from QP.limitations plus any setup-accepted gaps>
  ```

  Full detail belongs in `results.md`.

## Failure Report

When execution stops, return a short report (about 6 lines; full detail
goes in `results.md`), formatted as a debrief headed
`**❌ Step <k> · FAIL**` (or ⛔ BLOCKED / ⏹️ STOPPED BY USER, or `Setup · <check id>`
with the setup banner for a setup failure), with bullets for:

- exact agent name (or "parent setup"), attempt count and repair-cycle count;
- failed validation checks with the exact native error text;
- validated outputs completed before the failure, with links;
- relevant guidance from the template's troubleshooting section;
- what the user can do next, asked as a question with a recommended answer,
  an alternative and a free-form option.

Give no success-shaped final deliverable. Still write `results.md` and
`dispatch.json` stating FAIL, BLOCKED or STOPPED BY USER, and render the
report when Python is available.

---

## Quickstart Profile

> **Quickstart-specific section.** Replace everything below this line to run a
> different quickstart. Keep the field names; generic sections reference them
> as `QP.<field>`. Fields that do not apply should be set to `none`.

**Profile: CoreSPI specification-to-verified-RTL (profile
`corespi-app-win11-x64-dockerdesktop-v1.1`).**

### Identity and template

- `template`: [`knowledge/quickstart-template.md`](../../../knowledge/quickstart-template.md)
  (v1.1). Fixed prompt in section 6; runtime in section 7; troubleshooting in
  section 8.
- `goal`: A verified CoreSPI-inspired RTL controller with reference and
  implementation specifications, independent testbench, VCD, logs,
  `results.md` and HTML report under `results/<run-id>/`.
- `run_id_format`: `corespi-qs-<UTC yyyyMMddTHHmmssZ>-<8 hex>`.

### Setup inputs

- `agents`: `hardware-spec-dev`, `chip-rtl-design`, `chip-rtl-lint`,
  `chip-functional-verification` (all in `.github/agents/<name>.agent.md`).
- `forbidden_substitutes`: the `*-windows-docker-desktop` variants.
- `skills`: `report-gen`.
- `images` (Docker, Windows context `desktop-linux`):
  - `rtl-design:latest` — build context `discovery_catalog/chip-rtl-design/tools/rtl-design`
  - `rtl-lint:latest` — build context `discovery_catalog/chip-rtl-lint/tools/rtl-lint`
  - `functional-verification:latest` — build context `discovery_catalog/chip-functional-verification/tools/functional-verification`
- `external_tools`:
  - Microchip Catalog documentation search (live name such as
    `microchip-catalog-search_microchip_product_documents`), used by
    `hardware-spec-dev`. Probe: query `CoreSPI HB0089 handbook 5.2`, limit 10.
    Fallback: official HTTPS download only.
- `protected_files`:
  - `knowledge/CORESPI_HB.md`, written by Step 2. Context: "Keeping it
    matches the validated v1.1 run; replacing backs up the original first."
    P7 choices:
    `Keep it and append a run-provenance section only (Recommended)`,
    `Replace it with a new contract (original backed up)`.
- `scope_decisions`:
  - P8, asked when P7 chose replacement or the file is absent. Context: "The
    new contract must close handbook gaps; no vendor-equivalence is
    claimed." Question: "How should handbook gaps and options be
    resolved?" —
    `Full documented feature set, with explicit design decisions (Recommended)`,
    `Motorola SPI modes 0-3 only (master and slave, APB 32-bit)`.
- `bookshelf`: `Design-Best-Practices`, mode `always`. This quickstart is
  set up to use the Bookshelf: never ask whether to use it. This supersedes
  the template's "optional Bookshelf variant" wording; do not raise it as a
  template/profile conflict. Each agent saves queries, tool name and returned
  sources to a `BOOKSHELF.md` in its output folder, or states precisely that
  the tool was unavailable to it.

### Repair cycle

- `repair_cycle`: Steps 3-5, maximum 3 cycles. `artifact` = the final RTL
  file. Triggers: Step 4 lint/format failure, or a Step 5 failure with a
  reproducer attributed to the DUT. Testbench-only defects are corrected inside
  Step 5 and do not start a cycle.
- RTL path: `design/rtl/corespi.v` unless the Step 2 contract fixes another
  path under `results/<run-id>/`; a conflict is a runtime decision (Execution Rule 11).

### Steps

#### Step 1: Create the CoreSPI reference specification

- Briefing: Why: base the design on the official CoreSPI handbook, not
  memory. Who: `hardware-spec-dev`, using Microchip Catalog search.
  Discovery: a custom spec agent calling the connected Microchip Catalog MCP
  tool, grounded by the Design-Best-Practices Bookshelf. You'll get: `spec/CoreSPI.md` and the handbook PDF. Done when: the handbook
  version is confirmed and the spec has its port, parameter and register
  tables. Heads-up: several minutes.
- Agent: `hardware-spec-dev`
- Delegate: "Create the CoreSPI specification document. Project root is the
  current workspace. Run directory `results/<run-id>/`; create absent
  subfolders, never overwrite. Inspect your live tool inventory and use the
  Microchip Catalog documentation-search tool (exact IP handbook search by core
  name, handbook HB0089 and version) to find the governing CoreSPI handbook and
  applicable errata; follow returned official links and download the handbook
  via official HTTPS to `results/<run-id>/sources/CoreSPI_HB.pdf`. Verify the
  actual cover version and revision. Author an original, evidence-grounded
  specification at `results/<run-id>/spec/CoreSPI.md` with identity/scope,
  evidence and provenance, labeled functional requirements (vendor-defined,
  user-required or proposed) with measurable acceptance criteria,
  interfaces/parameters, operating behavior, register map, limits, integration
  guidance, an unexecuted acceptance checklist, open issues and sources. Save
  retrieval records to `results/<run-id>/retrieval/RETRIEVAL.md`, recording
  each tool call, query, application-level outcome, every HTTPS download and
  HTTP status. Do not modify `knowledge/`. Do not implement RTL or dispatch
  agents. Setup answers: <P6 and P9 answers>. Return the file paths, document
  version and revision, SHA-256 of the PDF, completeness (complete or
  partial) and blockers."
- Consumes: `(none)`
- Produces: `reference_spec` = { `spec/CoreSPI.md`, `sources/CoreSPI_HB.pdf`,
  `retrieval/RETRIEVAL.md`, version, revision, pdf_sha256 }
- Validation:
  - `spec/CoreSPI.md` exists, is nonempty, and every local Markdown link resolves.
  - `RETRIEVAL.md` records at least one Catalog documentation call with
    application-level success, unless P6 chose the fallback (then record the
    Catalog acceptance check as NOT met).
  - PDF exists, is nonempty, and its recorded SHA-256 matches the file.
  - Spec states the handbook number, core version and revision it read
    (reference: HB0089, CoreSPI v5.2, revision 6.0); a different revision is
    allowed only if explicitly reconciled.
  - Spec contains port, parameter and register tables and an open-issues section.

#### Step 2: Create the CORESPI_HB implementation contract

- Briefing: Why: turn the handbook into clear rules the RTL and testbench
  both follow. Who: `hardware-spec-dev`. Discovery: the same spec agent,
  writing into the project's knowledge folder. You'll get:
  `knowledge/CORESPI_HB.md` (plus a backup if replacing). Done when: no
  open questions remain. Heads-up: several minutes; you may be asked to
  decide a gap.
- Agent: `hardware-spec-dev`
- Delegate: "Create a specification markdown document in the knowledge
  directory for the CORESPI_HB device: `knowledge/CORESPI_HB.md`. CORESPI_HB
  names this project's original CoreSPI-inspired controller specification, not
  a separate vendor device. Inputs: `results/<run-id>/spec/CoreSPI.md`, its
  sources and retrieval record. P7 decision: <answer>. If keeping an existing
  file, do not change existing requirements; append only a section naming run
  `<run-id>`, linking the reference spec, handbook and retrieval record, and
  stating that new artifacts belong under `results/<run-id>/`. If replacing,
  first copy the original to `results/<run-id>/backup/CORESPI_HB.md` and
  verify its hash, then author a complete implementation contract using P8
  decision <answer>: top module `corespi`, all retained ports and parameters,
  register semantics, and an explicit, numbered original-decision table
  closing every handbook gap that affects externally observable behavior (APB
  side effects, FIFO full/empty, interrupts and W1C priority, reset/disable,
  protocol timing, synchronization latency). State the RTL file path and the
  authorized HDL language subset. If any consequential gap cannot be closed
  from the evidence and the P8 decision, list it under 'Unresolved' and do not
  claim the contract is implementation-ready. No vendor-equivalence claim.
  Freeze a copy at `results/<run-id>/spec/CORESPI_HB.frozen.md`. Return path,
  SHA-256 of both files, implementation readiness and unresolved items."
- Consumes: `Step 1: reference_spec`
- Produces: `implementation_contract` = { `knowledge/CORESPI_HB.md`,
  `spec/CORESPI_HB.frozen.md`, sha256, implementation_ready (bool), unresolved[] }
- Validation:
  - Both files exist, are nonempty and have identical SHA-256.
  - Contract names top module `corespi` and links the Step 1 reference spec.
  - `implementation_ready` is true and `unresolved` is empty. Otherwise pause
    and ask the user to decide each item (recommended answer, alternative,
    free-form), then retry Step 2 once with the decisions.
  - When P7 kept the file, all bytes before the appended section are unchanged
    from the setup SHA-256; when replaced, the backup hash equals it.

#### Step 3: Author RTL and run design checks

- Briefing: Why: write the Verilog design and prove it is clean,
  synthesizable logic. Who: `chip-rtl-design`, using Yosys. Discovery: a
  chip-design agent from the Agents catalog running its tool container,
  with Bookshelf guidance. You'll get:
  `corespi.v` and a design-check report. Done when: no latches or
  structural problems, and all legal configurations build. Heads-up: often
  tens of minutes.
- Agent: `chip-rtl-design`
- Delegate: "Read `knowledge/CORESPI_HB.md` completely (frozen copy
  `results/<run-id>/spec/CORESPI_HB.frozen.md`) and the reference spec. Create
  synthesizable Verilog for top `corespi` implementing every specified
  parameter, port and feature, using only the HDL subset the contract
  authorizes (disclose what you use). Save the final RTL at
  `results/<run-id>/<RTL path>`; version revisions under `design/revisions/`,
  never overwriting. Run `check_authored` with `rtl_files` in your installed
  `rtl-design:latest` image using fresh operation directories under
  `results/<run-id>/design/`, following your definition's immutable-input
  container contract. Also elaborate a representative legal parameter matrix
  covering every protocol family, APB widths, frame-width and FIFO-depth
  boundaries, and confirm illegal parameters are rejected. Repair real design
  defects; never weaken metrics or stub features. <Repair-cycle diagnostics,
  if any>. Do not dispatch other agents. Return final RTL path and SHA-256,
  final CDE path, tested matrix path and exact outcomes."
- Consumes: `Step 2: implementation_contract`
- Produces: `rtl` = { RTL path, rtl_sha256, final CDE path, tested-matrix path }
- Validation:
  - Final CDE: status `completed`, `validation.verdict` `pass`, container and
    Yosys exits 0, `synthesizable` true, inferred latches 0, check problems 0,
    reset and synchronizer gating findings 0, undriven and multidriven false.
  - CDE input hash equals the SHA-256 of the RTL file.
  - Every legal matrix case passed; illegal cases rejected as intended.

#### Step 4: Run DEFAULT lint and canonical formatting

- Briefing: Why: check the RTL against standard lint and formatting rules.
  Who: `chip-rtl-lint`, using Verible. Discovery: a lint agent running its
  tool container locally. You'll get: a lint report. Done when:
  zero violations and the file is already correctly formatted. Heads-up: a
  few minutes; a failure sends the RTL back to Step 3.
- Agent: `chip-rtl-lint`
- Delegate: "Gate the immutable RTL `results/<run-id>/<RTL path>` (expected
  SHA-256 <rtl_sha256>) in a fresh operation directory
  `results/<run-id>/lint-<n>/` using your installed `rtl-lint:latest` image with
  params `{\"scenario\":\"lint_gate\",\"sources\":[\"/input/corespi.v\"],\"ruleset\":\"default\",\"format_gating\":true,\"indentation_spaces\":2}`.
  No waivers, rule overrides or config search. Verify the RTL hash before and
  after. If anything fails, return the exact per-rule findings and a saved
  proposed fix without adopting it, and state whether the fix would conflict
  with the contract's authorized HDL subset. Do not dispatch agents. Return
  CDE path, container exit, lint violation count, unformatted-file count and
  hashes."
- Consumes: `Step 3: rtl`
- Produces: `lint_result` = { CDE path, lint_violations, unformatted_files,
  rtl_sha256 }
- Validation:
  - Container exit 0; CDE `completed` / `pass`.
  - `lint_violations` = 0 and `unformatted_files` = 0; native Verible exits 0.
  - `sources_unchanged` true and hash equals Step 3 `rtl_sha256`.
  - On failure: start a new repair cycle (Execution Rule 9).

#### Step 5: Verify with an independent testbench, simulation and VCD

- Briefing: Why: prove the design behaves as specified, using a testbench
  written from the spec. Who: `chip-functional-verification`, using Icarus
  Verilog. Discovery: a verification agent running its simulator
  container, with Bookshelf guidance. You'll get: the testbench, simulation log and VCD waveform. Done
  when: zero mismatches and `TEST PASSED`. Heads-up: often tens of minutes;
  a design bug sends the RTL back to Step 3.
- Agent: `chip-functional-verification`
- Delegate: "Create an independent, self-checking testbench (module `tb`) for
  the frozen DUT `results/<run-id>/<RTL path>` (SHA-256 <rtl_sha256>) derived
  from `knowledge/CORESPI_HB.md` and the reference spec, never from RTL
  internals. Exercise protocol families, master and slave roles, Motorola
  modes 0-3, custom options, APB chunking widths, FIFO boundaries including
  non-power-of-two depths, interrupts and W1C races, reset, disable, packet
  boundaries and divider limits. Use a bounded watchdog, explicit comparison
  accounting, exactly one `COMPARISONS=n MISMATCHES=m` summary and a
  standalone `TEST PASSED`; on failure print `TEST FAILED` and `$fatal`. Run
  `run_sim` (top `tb`, generation 2012, wave_format vcd) in your installed
  `functional-verification:latest` image in fresh `results/<run-id>/sim-<n>/`
  directories. Correct only testbench defects, preserving every attempt. If
  the DUT is wrong, return a minimal failing reproducer, log, VCD and the
  violated requirement. Save the configuration and requirements matrix with
  explicit omissions. Never edit the DUT. Return testbench, VCD, logs, CDE,
  matrix paths, counts and hashes."
- Consumes: `Step 3: rtl`, `Step 4: lint_result`
- Produces: `sim_result` = { testbench path, VCD path, vvp log, CDE path,
  comparisons, mismatches, requirements matrix path }
- Validation:
  - Container, iverilog and vvp exits 0; CDE `completed` / `pass`;
    `sim_passed` true.
  - Log has exactly one `COMPARISONS=n MISMATCHES=0` with n > 0, an exact
    `TEST PASSED` line, and no `TEST FAILED`, `FATAL` or `ERROR` markers.
  - VCD exists and is nonempty.
  - CDE DUT input hash equals Step 3 `rtl_sha256`.
  - On a DUT-attributed failure: start a new repair cycle (Execution Rule 9).

### Final validation inputs

- `deliverables`: `spec/CoreSPI.md`, `knowledge/CORESPI_HB.md`, the final RTL,
  the final testbench, the final VCD, and design, lint and simulation logs.
- `verdict_rule`: PASS only when design checks, lint, formatting and
  simulation all pass on identical final RTL; otherwise report the actual
  failure.
- `report_skill`: `report-gen` (`results.json` per-stage evidence with `cde`
  and `execution_evidence`, plus `dispatch_record`).
- `report_notes`: if `report-gen` exits 2 only because the VCD exceeds the
  default record limit, render a new file with an explicit higher
  `--max-changes`.
- `final_links`: reference spec, `knowledge/CORESPI_HB.md`, RTL, testbench,
  VCD, simulation log, `results.md` and HTML report.
- `limitations`: sampled functional verification only; no vendor CoreSPI
  equivalence, CDC/RDC, timing or physical signoff; disclose any
  SystemVerilog-subset use; asynchronous `PRESETN` release is an integration
  responsibility.
