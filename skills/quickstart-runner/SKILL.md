---
name: quickstart-runner
description: >-
  Follow a supplied full QuickStart Scenario guide and its exact input files
  from a fresh Discovery project. Use for run this QuickStart, BioPharma,
  SiPhy, CMS or Bookshelf setup. Check readiness, obtain separate setup and
  execution approvals, and validate actual outputs. Do not replace the guide
  with a generated profile or infer permission from examples.
compatibility: Requires file and command tools and the capabilities stated by the selected full guide. Author-only download preparation uses Python 3.10+.
metadata:
   author: QuickStart Scenarios contributors
  version: "0.2.0"
---

# QuickStart Scenarios runner

This is the shared runner. The original scenario skill remains unchanged with the
SiPhy files; this adaptation is separately identified and still awaiting an
end-to-end test. **The selected full QuickStart Markdown is authoritative.**
Do not shorten it, rewrite its science/prompt, replace it with a generated
manifest/profile, or execute a different scenario because setup is difficult.

## Start

1. Read the full guide the user attached or selected and the adjacent README.
   If no completed guide exists, say so and stop; do not invent one at runtime.
2. Identify its exact version, model, default scope, input filenames, skill and
   native success checks. Only the chosen guide supplies scenario rules.
3. Inspect the new project and user-supplied file locations. Do not use earlier
   sessions, environments, cached indexes or another person's project as inputs.
   Historical output links are reference evidence, never new-run results.

## One-time setup

Show **One-time setup — computation has not started**. Collect independently
observable readiness checks: OS/CPU architecture, interpreter version/path,
model, required tools/agents, exact input file hashes, space and destination.
Show missing/mismatched/unknown items together in normal chat. Do not infer
capability activation from files on disk or content readiness from a health dot.

Ask for the guide's dependency selection in its required channel. Ordinary-chat
Yes/No stays ordinary chat. Show its full required dependency list even when
another check is blocked. Selection is not installation or computation approval.
Do not blindly recommend Allow for every host permission prompt.

Python must be obtained from the version/platform-specific publisher source
when missing; pip installs Python packages, not the interpreter. Do not silently
change pins, install latest, remove another Python, disable TLS or bypass policy.
Recheck the actual interpreter after the user resolves a mismatch.

Before installing: verify the supplied archives and complete member manifests,
obtain permission for a short new destination and safe extraction, and never
overwrite an existing file. Preserve nested paths, original archive bytes,
checksum attachments and the full guide. If the guide says the launcher
extracts a snapshot itself, leave that archive unopened. An older bundled guide
remains at its manifest path but does not override the selected newer guide.

After source/runtime/destination checks pass, separately request installation
approval for exactly the guide's set and required transitives, including any
unlocked versions. Report the package index without credentials. Use the supplied
setup command when one exists; do not invent a duplicate requirements file or
partial install. Verify its printed interpreter, package checks and native
preflight. Keep approvals scoped to the actual set, version and destination.

For Bookshelf/configuration work, obtain its own appropriate approval and record
the exact source/index settings. Agent probes and indexing may use resources;
they are not automatically read-only. Required missing rights, bindings or input
content stop the run. Publicly visible paper URLs do not waive publisher terms.

## Run

Ask autonomous end-to-end versus walk-through when setup is complete. Mode is
not consent. Before scientific execution obtain the guide's separate bounded
approval with actual scope, resource limits, exclusions and measured historical
timing distinguished from estimates. No inherited or example approvals.

Explain every phase: **Why / Who / Outputs / Done when / Heads-up**; in
walk-through mode wait for that phase's confirmation. Follow the guide's exact
prompt, responsible parent/specialist roles and sequence. Validate native outputs
before handoff. Never use local commands as substitutes for a required agent.

Respect guide-specific exclusions and retry rules. If it records no run-wide
retry/time budget, agree one before long work rather than inherit an older
skill's policy. No automatic new investigation or workload to diagnose silence.
Use host completion notifications and the guide's observation cadence; do not
poll aggressively or invent a guarantee from one historical duration.

Honor Stop and safety issues. Preserve failed attempts and checkpoints; do not
delete shared resources/locks or restart compute without inspecting ownership
and obtaining applicable approval. Do not automatically deploy cloud resources,
change grants, publish files or sign in on the user's behalf.

## Finish

Check the actual guide-defined output artifacts, native receipts, citations and
required human/scientific review. Report **environment readiness**, **workflow
completion** and **scientific acceptance** separately. A model's prose, file
existence, historical report or metadata record is not proof of execution.

Return real output links and failures/caveats. A native-gate pass does not erase
requirement-coverage limitations. Report unrun work as unrun. Do not change the
owner's guide or success criteria to make the run pass.