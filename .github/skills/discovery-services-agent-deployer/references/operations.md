# Operations

## Runner model

The public entrypoint is:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-services-agent-deployer/scripts/deploy-discovery-agent.ps1 <agent-name>
```

The runner is a single self-contained PowerShell script and owns:

1. Agent/tool discovery
2. Copilot-style config input request when local config is missing or incomplete
3. Build mode selection
4. Image build and ACR push
5. Tool ARM deployment
6. Agent YAML patching and deployment
7. Validation investigation
8. Final summary

Only `scripts/deploy-discovery-agent.ps1` is used for deployment logic. Keep new stage behavior in that script rather than adding separate internal stage scripts, so this skill stays aligned with the single-script `discovery-services-starter-kit-deployer` layout.

## Stage-at-a-time execution

Native Copilot TODOs update when the assistant regains control between terminal commands. If the user expects the VS Code Copilot TODO list to advance during deployment, run one stage per command with `-Stage` rather than one long end-to-end command:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-services-agent-deployer/scripts/deploy-discovery-agent.ps1 chembl -Stage init
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-services-agent-deployer/scripts/deploy-discovery-agent.ps1 -RunDir <RunDir> -Stage build
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-services-agent-deployer/scripts/deploy-discovery-agent.ps1 -RunDir <RunDir> -Stage deploy-tool
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-services-agent-deployer/scripts/deploy-discovery-agent.ps1 -RunDir <RunDir> -Stage deploy-agent
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-services-agent-deployer/scripts/deploy-discovery-agent.ps1 -RunDir <RunDir> -Stage validate
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-services-agent-deployer/scripts/deploy-discovery-agent.ps1 -RunDir <RunDir> -Stage summary
```

Update the native TODO item before and after each command. After `TASK_STATUS=deploy-agent:done`, mark `deploy-agent` done before running validation. After `TASK_STATUS=validate:done`, mark `validate` done before running summary. After `TASK_STATUS=summary:done`, mark `summary` done before posting the final success response. The end-to-end runner is still useful for automation or environments without native TODO UI, but it cannot force the Copilot UI to advance while a single long terminal command is still running.

## Checkpoints

Each run writes `run-state.json` under `agents/tmp/<agent>/<timestamp>/`. The final summary reads that state and prints deterministic `SUMMARY_*` lines. Keep the run folder until the deployment is known-good.

## Resume

Use `-Resume <RunDir>` after fixing a failed prerequisite, permission issue, transient Azure failure, or validation timeout:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-services-agent-deployer/scripts/deploy-discovery-agent.ps1 -Resume agents/tmp/<agent>/<timestamp>
```

The runner skips completed stages based on `run-state.json` and continues from the next incomplete stage.

## Stage TODO status

When the assistant environment exposes a native task/TODO UI, such as the VS Code GitHub Copilot prompt-window TODO list, use that UI as the primary progress tracker. First validate every requested agent exists under `agents/microsoft/<agent>` or `agents/partners/<partner-name>/<agent>`. If any agent is missing or ambiguous, do not create deployment TODOs; stop and ask the user to fix the agent name or specify `-PublisherName`.

After all requested agents pass preflight validation, create one item per visible deployment stage before starting the long-running deployment work and update each item as the runner reaches that stage. Tool-backed agents use:

1. `init`
2. `build`
3. `deploy-tool`
4. `deploy-agent`
5. `validate`
6. `summary`

Agents without a `tools/` folder are still deployable. For those agents, `build` and `deploy-tool` are expected to emit `TASK_STATUS=<stage>:skipped`, and the deployment continues with `deploy-agent`, `validate`, and `summary`.
The runner also prints `[runner] Stage 2 and stage 3 skipped as the agent doesn't have any tool.` so users understand why the visible flow moves from stage 1 to stage 4.

For agents without tools, create only four native TODOs:

1. `init`
2. `deploy-agent`
3. `validate`
4. `summary`

The runner cannot directly update the VS Code Copilot TODO UI; the assistant invoking the skill is responsible for creating and updating those tasks. To avoid duplicate progress noise, the runner does not print a separate checklist. It emits concise `[runner] START`, `[runner] DONE`, and `[runner] SKIP` lines, deterministic `SUMMARY_*` output, and explicit machine-readable progress lines:

```text
TASK_STATUS=build:in_progress
TASK_STATUS=build:done
TASK_STATUS=deploy-tool:failed
TASK_STATUS=validate:skipped
```

Use `TASK_STATUS` lines as the primary signal for the native Copilot TODO list. The assistant must reconcile the visible TODO UI with every `TASK_STATUS` line before continuing to the next stage or reporting final success. On resume, skipped completed stages emit `TASK_STATUS=<stage>:done` before the `[runner] SKIP ... (already completed)` line so stale TODOs can be corrected.

The runner emits `TASK_PLAN=<agent>/<stage>` lines immediately after successful preflight validation. These lines do not mean a stage started; they are a deterministic plan signal for assistants that need a concrete trigger to create the native TODO list before the first `TASK_STATUS=...:in_progress`. Agents without tools emit only `init`, `deploy-agent`, `validate`, and `summary` plan lines.

## Multiple agents

When the positional agent list or `-AgentName` contains two or more names, the runner executes them sequentially and tags every child-run log line. Slash-style requests should map directly to positional names:

```text
/discovery-services-agent-deployer chembl aizynthfinder
```

Invoke the runner as:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-services-agent-deployer/scripts/deploy-discovery-agent.ps1 chembl aizynthfinder
```

```text
[multi-agent] COUNT=2
[multi-agent] AGENTS=chembl,aizynthfinder
[agent:chembl] [runner] START stage-01-init
[agent:aizynthfinder] [runner] START stage-01-init
```

Create native Copilot TODOs as one six-stage set per agent:

1. `chembl / init`
2. `chembl / build`
3. `chembl / deploy-tool`
4. `chembl / deploy-agent`
5. `chembl / validate`
6. `chembl / summary`

Repeat the same labels for each requested agent. Multi-agent task signals include the agent name:

```text
TASK_STATUS=chembl/build:in_progress
TASK_STATUS=chembl/build:done
TASK_STATUS=aizynthfinder/deploy-tool:failed
```

Use the `<agent>/<stage>` prefix to update the matching TODO. A failed agent is reported as `[multi-agent] FAILED agent=<name> exitCode=<code>` and the runner continues to the next requested agent before returning a final failure for the overall multi-agent batch.

The multi-agent wrapper must stream each child runner line as it is produced. Do not capture child output into an array before printing it, because that prevents `TASK_STATUS` updates from reaching the native Copilot TODO UI until the entire child deployment exits.

- `pending`: stage has not started yet.
- `in_progress`: stage is currently running.
- `done`: stage completed or was already complete during resume.
- `skipped`: stage was intentionally skipped, such as validation with `-SkipValidation`.
- `failed`: stage failed and needs attention before resume.
- `input_required`: stage stopped cleanly because Copilot needs to collect missing config values from the user.

For Supercomputer nodepool confirmation, `input_required` must be handled with the assistant choice-prompt UI, not a plain text question. Use the question from the `COPILOT SUPERCOMPUTER NODEPOOL INPUT REQUEST` block and present exactly these two choices: `Proceed - I have Supercomputer nodepool capacity for at least one listed SKU.` and `Stop - I do not have the required Supercomputer nodepool capacity.` Only rerun build with `-ConfirmSupercomputerNodepools` after the customer selects Proceed.

The same status is written to `stage-todos.json` in the run directory. Use that file for automation, resume-aware progress, or reporting after a long run:

```powershell
Get-Content agents/tmp/<agent>/<timestamp>/stage-todos.json -Raw | ConvertFrom-Json
```

Validation requires the response to complete and not report an execution failure. A completed conversation that says tool execution failed, for example a `Bad Request`, `InvalidNodepool`, or `NodepoolCapabilityError`, is a failed validation and should mark the `validate` TODO as failed. A completed response with valid output is a passed validation even if the output contains Unicode characters; the runner writes preview output as UTF-8 so console encoding must not turn a passed validation into a failed stage. Prompt priority is explicit `-ValidationPrompt`, then non-empty config `testPrompt`, then Copilot-generated prompt. For tool-backed agents, generate a short, concrete validation prompt from the agent/tool context and pass it with `-ValidationPrompt` when no config override exists; if the runner emits `VALIDATION_PROMPT_INPUT_REQUIRED=true`, generate the prompt yourself and rerun validation. Agents without tools validate with `What can you do?` unless the caller passes an explicit validation prompt. Validation investigations are retained by default; set `deleteInvestigationAfterTest` to `true` only when the customer explicitly wants cleanup after validation.

## Build modes

- `auto`: if Docker is available, ask the user for `remote` or `local` as a per-run Copilot input and rerun with `-BuildMode`; if Docker is unavailable, use remote.
- `remote`: use ACR Tasks. Best default for customer machines without Docker.
- `local`: use local Docker, then push to ACR.

Use `-WhatIfPlan` to inspect repo discovery and planned stages without Azure calls.

