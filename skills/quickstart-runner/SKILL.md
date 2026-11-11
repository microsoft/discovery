---
name: quickstart-runner
description: >-
  Guide one selected QuickStart Scenario from fresh-project readiness through
  separately approved setup and bounded execution. Use for run this quickstart,
  QuickStart Scenarios, SiPhy, BioPharma, CMS, or Bookshelf scenario setup.
  Read the supplied versioned guide and profile; stop on unresolved draft
  blockers. Not a cloud deployer, scenario author or permission bypass.
compatibility: Requires a host with local file/command tools; execution additionally needs the scenario's declared Discovery capabilities. Packaging helpers use Python 3.10+ standard library only.
metadata:
  author: Discovery QuickStart Scenarios contributors
  version: "0.1.0"
---

# QuickStart Scenarios runner

**Draft; customer-path activation and execution not yet validated.** Adapted
from Joe's supplied `quickstart-siphy-spec2rtl-1` design: immediate prerequisite
checks, separate setup banner, phase explanations, autonomous/walk-through
modes, ordered handoffs and evidence-based reporting. Scenario logic is outside
this skill. Attribution does not replace contributor/publication review.

Read [the execution protocol](references/execution.md) before acting. The
[README](README.md) explains packaging and limitations. The prototype formerly
kept in a personal skills folder is not a dependency of this package.

## 1. Resolve the scenario without guessing

1. Read the explicitly selected scenario's `scenario.json`, `README.md`,
   `profile.md` and exact prompt. A staged project has
   `quickstart-selection.json` at its root. Resolve that record relative to
   the **project root**, not the skill folder. Otherwise ask which of the
   available scenario guides the user intends. Never silently default to a
   chip-design profile or infer readiness from the conversation title.
2. Verify manifest and prompt integrity using the supplied packaging helper
   in the repository before staging. For a staged project inspect its
   `staged-files.json`; verify its hashes before using executable content.
   A locally generated digest proves consistency, not publisher authenticity.
3. Keep the guide's science, fixed prompt and owner acceptance checks unchanged.
   If guide/profile/source disagree, stop and identify the conflict rather
   than choose the less restrictive rule. Do not repair the scenario at run time.
4. A draft can be inspected. Show its unresolved blockers first. Missing
   components, missing rights, unapproved prompts or unknown required settings
   stop execution. `--allow-draft` is only a packaging preview, never consent
   or a way to bypass these blockers.

## 2. Inspect readiness immediately

Start with **One-time setup — preparing the environment; computation has not
started.** Collect independent read-only checks together: host/App version,
OS and hardware architecture, interpreter version/bitness/path, supplied asset
hashes, free storage and target location, tool/agent availability, and corpus
readiness when applicable. Distinguish Unknown, Missing and Mismatched.

Show one short `Item | Observed | Required action` table in normal chat.
Do not install, index, extract, dispatch agents or load serialized models as a
readiness probe. An agent lookup that invokes a hosted model is not a free
read-only check. File presence and a green index status do not prove activation
or usable document text.

The scenario's platform declaration governs. App installers for a platform
are not evidence this scenario works there. Do not offer emulation, a runtime
downgrade, system-Python removal or a different dependency set as an automatic
fix. Give the exact publisher/version option and wait for an explicit decision;
verify the resulting interpreter instead of trusting PATH or an alias.

## 3. Apply separate decisions in the correct order

The profile declares the question channel and scope. Plain Yes/No dependency
selection requested in ordinary chat must remain ordinary chat, not a card or
form. Show every required item and its purpose, including already-installed
items. A selection does **not** authorize installation or computation.

Obtain distinct, scoped approvals as applicable for:

1. Asset acquisition/staging (destinations, integrity, licences, no overwrite).
2. Runtime or dependency installation (exact versions, destination and necessary
   transitive dependencies; explain any incompletely locked dependencies).
3. Bookshelf creation/indexing or capability configuration (corpus, cost and
   available permissions; never self-grant access).
4. Scientific/agent execution, after setup and native preflight pass (fixed
   steps, resource bounds, time expectations and exclusions).

Do not obtain installation approval before the destination is known; do not
run a launcher's preflight before verifying its source and inputs. A package
download or file-tool permission prompt is not a scientific approval. When an
authorized run-owned environment satisfies all pins, skip needless installation
but retain the scenario's required dependency selection and compute decision.

Ask for autonomous end-to-end or walk-through **after setup**; mode selection
does not grant any approval. Recommend a mode with an alternative and a Stop
option. Autonomous means no unnecessary checkpoints, not no safety boundaries.

## 4. Execute the profile, not an improvised workflow

- Execute the fixed steps in order, one at a time; honor each step's declared
  `local` or named-agent role. Never substitute one for the other.
- Before every phase show Why / Who / Discovery capability / Outputs / Done
  when / Heads-up. In walk-through mode wait for permission for that phase.
  Use plain text in dialogs, Markdown in chat. Debrief each actual result.
- Apply the scenario's retry/repair rules. Default to **no retry** when absent;
  a profile may name a finite repair cycle. A successful retry does not erase
  the initial failure. Never weaken a failed check.
- Keep output locations explicitly declared. A native launcher may own
  `runs/<id>/` while the coordinator owns `results/<id>/`; link them, never
  move or merge their trees. App-managed chat state may live under `sessions/`;
  scientific outputs must not be hidden there.
- Enforce scenario exclusions, including any ban on CLIO/investigation or
  fresh data. Do not start extra work to diagnose a quiet launcher. Explain
  measured historical silent periods as observations, not guaranteed timers.
  Use host completion notifications where available; no rapid polling or
  artificial sleep loops. Follow the profile's evidence-read cadence.
- Honor user cancellation and new safety issues immediately. Do not overwrite
  or delete an old run, stale lock, environment, shelf or shared resource.
  Recovery requires inspected native state and appropriate approval.

## 5. Report evidence, never assumed success

Keep three statuses separate: **environment readiness**, **workflow completion**
and **scientific acceptance**. Validate actual artifacts and native receipts,
including required tool paths, not just model prose or file existence.
Reference results bundled with the inputs are never a new run's results.

Record versions, source/prompt/input hashes, selected profile, native run IDs,
approval scope and actual outcomes under the run-owned evidence folder. Retain
failed/unrun checks and limitations. Do not inherit approvals from another
chat or a sample in the guide. End with PASS only if the owner's full required
criteria passed; otherwise use BLOCKED, FAILED, STOPPED or NEEDS OWNER REVIEW.
Link partial outputs honestly, without a success-shaped final deliverable.

Never upload private logs or papers, enable telemetry, deploy, publish a PR,
or change authentication as part of this skill. Sign-in remains under the
user's control in their external browser.