---
name: discovery-services-starter-kit-deployer
description: 'Deploy Discovery catalog starter-kits end-to-end: validate kit.json agentRefs, build and deploy every referenced agent tool, deploy each referenced agent individually, and summarize deployed agents/tools plus customer-ready sample prompts. Use this skill whenever the user asks to deploy a Discovery starter-kit or deploy all agents listed in starter-kits/*/kit.json.'
allowed-tools: shell
---

# Discovery Starter-Kit Deployer

## Compatibility

Runs on Windows, macOS, and Linux through PowerShell 7+ (`pwsh`). Requires `git`, `python` with `pip`, and Azure CLI (`az`). Docker is optional because the runner can use Azure Container Registry Tasks when local Docker is unavailable.

## What this skill does

Deploy a starter-kit from `starter-kits\` as individual Discovery prompt agents:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 <starter-kit-name>
```

The runner reads `starter-kits\<starter-kit>\kit.json`, validates every top-level `agentRefs[].ref` resolves to an existing `agents\<agent>\` folder, builds every tool from those agents, deploys the tool resources in parallel, patches each referenced source agent with its own deployed tool resource ids, deploys all referenced agents in parallel, and prints a summary of deployed agents, deployed tools, and all top-level `samplePrompts` the customer can run manually.

## When to use

Use this skill for requests like:

- "/discovery-services-starter-kit-deployer `drug-discovery`"
- "Deploy the `protein-structure-analysis` starter-kit"
- "Deploy the agents in this starter-kit"
- "Deploy all agents referenced by this starter-kit kit.json"

If the user only wants one agent deployed, use `discovery-services-agent-deployer` instead. If the user only wants inventory, use `discovery-catalog`.

## Customer inputs

| Parameter | Purpose |
|---|---|
| `<starter-kit-name>` or `-StarterKitName <name>` | Starter-kit folder name directly under `starter-kits/`. Required for `init` and `-WhatIfPlan`. |
| `-PublisherName <name>` | **Deprecated.** Tolerated for backwards compatibility but ignored — kits live in the flat `starter-kits/<kit-name>/` layout with no publisher folder. The deployer prints a one-line deprecation notice when the flag is supplied. |
| `-BuildMode remote\|local` | Required for every new starter-kit deployment during `init`; ask the customer to choose. `remote` queues ACR builds; `local` uses local Docker and pushes to ACR. Do not store build mode in `config.json`. |
| `-Stage init\|build-tools\|deploy-tools\|deploy-agent\|summary\|stop` | Runs exactly one stage so Copilot TODOs can advance between commands. |
| `-RunDir <RunDir>` | Required with `-Stage` after `init`. |
| `-KnowledgeBasesJson <json-or-path>` | Required during `init` when any referenced agent declares `discoveryExtensions.knowledgeBases`. Pass either inline JSON or a path to a JSON file keyed by agent name. |
| `-ConfirmSupercomputerNodepools` | Run-scoped confirmation that the customer chose Proceed for the current run's tool/SKU plan. Pass it to `init` if the confirmation was collected before the run directory is created, or to the rerun of `build-tools` if the runner requested confirmation there. Do not store this in `config.json`. |
| `-WhatIfPlan` | Prints kit discovery, agentRefs, and stage plan without Azure calls. |

Local environment values live in `.github\skills\discovery-services-starter-kit-deployer\config.json`, copied from `config.template.json`. If that file is absent, the runner falls back to `.github\skills\discovery-services-agent-deployer\config.json` for the shared Azure/Discovery settings; starter-kit config values override the fallback when both files exist. The populated files are intentionally gitignored; never commit them. Build mode and Supercomputer nodepool confirmation are per-run choices, not config values; never write `buildMode` or `confirmSupercomputerNodepools` to `config.json`, and ignore/remove stale copies if they are present from older runs. During full deployment `init`, the runner checks required config before asking for build mode. If it emits `CONFIG_INPUT_REQUIRED=true`, ask the user only for the fields listed in `CONFIG_FIELDS_TO_COLLECT`, keep the optional defaults shown in the suggested config shape, write the ignored starter-kit `config.json` only when the fallback does not already provide the values, and rerun `init`. Only after config is complete, if the runner emits `BUILD_MODE_INPUT_REQUIRED=true`, ask the customer to choose `remote` or `local`, then rerun `init` with `-BuildMode <choice>`. For build-tools, first show the tool/SKU nodepool plan and collect the Proceed/Stop decision before asking for Azure build config. build/deploy-tools need `subscriptionId`, `resourceGroup`, `acrName`, and `location`; set optional `acrResourceGroup` when the ACR registry is in a different resource group than the Discovery deployment resources. `forceToolImageRebuild` must be explicitly present in either deployer config; set it to `true` only when `build-tools` should rebuild and repush images even if the same repository:tag already exists in ACR, otherwise set it to `false`. deploy-agent needs `workspaceEndpoint`, `project`, `tenantId`, and `chatModel`. Do not invent missing values.

When `.github\skills\discovery-services-starter-kit-deployer\config.json` is missing or still contains template placeholders, ask the customer for these values and create the ignored config file:

| Config field | Ask the customer for |
|---|---|
| `subscriptionId` | Azure subscription id that contains the Discovery resources and ACR. |
| `resourceGroup` | Resource group for Discovery tool and agent resources. |
| `acrName` | Azure Container Registry name without `.azurecr.io`. |
| `acrResourceGroup` | Optional ACR resource group when different from `resourceGroup`; otherwise use the same value as `resourceGroup`. |
| `location` | Discovery region. Present `eastus`, `swedencentral`, and `uksouth` as the supported choices, and allow a freeform text value only for future expansion or explicit customer override. |
| `workspaceEndpoint` | Discovery workspace endpoint, for example `https://<workspace>.workspace.discovery.azure.com`. |
| `project` | Discovery project name. |
| `tenantId` | Azure tenant id GUID. |
| `chatModel` | Chat model deployment name for the deployed agents. |
| `forceToolImageRebuild` | Whether to rebuild tool images even when the same ACR repository:tag already exists; ask explicitly and default to `false` unless the customer asks to force rebuilds. |

For `location`, use a multiple-choice prompt with `eastus`, `swedencentral`, and `uksouth`, while still allowing freeform input. Discovery currently supports only those three regions; treat any other value as an explicit future-expansion override from the customer.

## Workflow

1. For planning or uncertain names, run `-WhatIfPlan` first.
2. Validate the starter-kit exists at `starter-kits\<starter-kit>\kit.json`.
3. Parse `agentRefs[].ref` and ensure every referenced `agents\<agent>\agent.yaml` exists before creating deployment TODOs.
4. Create the native Copilot TODO list only after starter-kit preflight succeeds.
5. Run stages from the repo root. Keep all starter-kit-level run artifacts under `starter-kits\tmp\<starter-kit>\<timestamp>\`. For every new starter-kit run, choose `remote` or `local` build mode during `init`; do not let `auto` proceed silently.
6. During `init`, the runner scans every referenced `agent.yaml` for `discoveryExtensions.knowledgeBases`. Knowledge bases are not deployed by this skill. If any are declared, the runner emits `KNOWLEDGE_BASE_INPUT_REQUIRED=true` plus one `KNOWLEDGE_BASE_REQUIRED agent=<name> count=<n>` line per affected agent and a suggested JSON shape. Ask the user to provide the actual `knowledgeBaseId` values in `/bookshelves/{bookshelf_name}/knowledgeBases/{knowledgebase_name}/versions/{version}` format, save them to a temporary JSON file or pass inline JSON, and rerun `init` with `-KnowledgeBasesJson <json-or-path>`. The JSON must be keyed by agent name and each value must be an array of objects with `knowledgeBaseId`; the runner stores these values in `run-state.json` and patches each agent before deployment.
7. Before building tools, run the runner's `build-tools` stage without `-ConfirmSupercomputerNodepools` so it prints the authoritative `TOOL_BUILD_PLAN` lines, writes `<RunDir>\build-plan.json`, and pauses with `TASK_STATUS=build-tools:input_required`. Do not use `rg`, `grep`, or ad-hoc file scanning to inspect generated `tool.yaml` files; those tools may not be installed in the customer's shell, and the runner already parses `recommended_sku` choices consistently. Show the customer every tool image and the `recommendedSkus` choices from the `TOOL_BUILD_PLAN` output or `BUILD_PLAN_JSON` path. Explain that the SKUs listed for a tool are alternative nodepool choices, not cumulative requirements; the customer needs capacity for at least one listed SKU per tool. Then ask whether to proceed or stop based on their Supercomputer nodepool capacity. Use `ask_user` with choices `Proceed - I have Supercomputer nodepool capacity for at least one listed SKU per tool` and `Stop - I do not have the required Supercomputer nodepool capacity`. Ask this at most once per run. If they choose Proceed after `build-tools` requested confirmation, rerun `build-tools` with `-ConfirmSupercomputerNodepools`; do not persist that confirmation in `config.json` because it must be reconfirmed for every new starter-kit run. If they choose Stop, do not run `build-tools`; immediately run `-Stage stop -RunDir <RunDir>` so the runner emits `TASK_STATUS=<stage>:stopped` for every full-deployment task (`init`, `build-tools`, `deploy-tools`, `deploy-agent`, `summary`), even if `init` had already completed. Existing ACR tags are reused by default; `forceToolImageRebuild: true` overrides reuse and queues a rebuild for the same tag. In remote mode, submit all required ACR builds first, then track every run independently; if any build fails, stop the deployment and report the failed tool list. Agents without `tools\*\tool.yaml` are recorded as skipped.
8. Deploy every built tool in the `deploy-tools` stage and capture each `Microsoft.Discovery/tools/<tool>` resource id. The runner deploys tool resources in parallel.
9. Deploy every referenced source agent individually in the `deploy-agent` stage. The runner patches each agent's `discoveryExtensions.tools` to point to the tool resources deployed for that agent, patches `discoveryExtensions.knowledgeBases` with user-provided knowledge base ids when required, writes run-local patched YAML files under `<RunDir>\agents\`, and upserts the agents in parallel. It does not synthesize a combined starter-kit agent.
10. Do not create an investigation as part of starter-kit deployment. The final summary lists the sample prompts the customer can run after deployment.
11. Report only the final summary printed by the runner.

## Copilot task tracking

When a TODO UI is visible, create these starter-kit TODOs after `kit.json` and `agentRefs` pass preflight:

For full deployment requests, create:

1. `init` - discover starter-kit, validate plugin, collect config, create `starter-kits\tmp\<starter-kit>\<timestamp>`
2. `build-tools` - build and push all referenced agent tool images
3. `deploy-tools` - create or update every Discovery tool resource in parallel
4. `deploy-agent` - deploy every referenced agent individually in parallel
5. `summary` - print deployed agents, tools, and customer-ready prompts

Run stage-at-a-time when TODOs are visible:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 drug-discovery -Stage init
pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 -RunDir <RunDir> -Stage build-tools
pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 -RunDir <RunDir> -Stage deploy-tools
pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 -RunDir <RunDir> -Stage deploy-agent
pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 -RunDir <RunDir> -Stage summary
```

If the customer chooses Stop at the Supercomputer nodepool confirmation prompt, run:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github\skills\discovery-services-starter-kit-deployer\scripts\deploy-discovery-starter-kit.ps1 -RunDir <RunDir> -Stage stop
```

Mark each TODO done only after the command exits successfully or emits `TASK_STATUS=<stage>:done`. If the runner emits `TASK_STATUS=<stage>:input_required`, keep that stage as waiting for input rather than failed, collect only the fields or confirmation requested by the runner, then rerun the same stage with `-RunDir <RunDir>`. If a stage fails, mark it failed and report the exact stage command with `-RunDir <RunDir>`.

## Reporting contract

When the runner completes, summarize:

- `RUN_DIR`
- `STARTER_KIT`
- referenced `AGENTS`
- stage statuses from `stage-todos.json` and summary output
- deployed `AGENT_DEPLOYED` names and run-local `AGENT_YAML` files
- deployed `TOOL_DEPLOYED` values
- numbered, complete sample prompts from `kit.json`, introduced with "You can now try any of the following prompts to test the deployment:"


If the runner fails, report the failed stage and required action from the output. Include the exact stage command with `-RunDir <RunDir>` for recoverable failures, except when the customer chose Stop for Supercomputer nodepool capacity; in that case, do not provide a direct PowerShell rerun command and say exactly: "When you have Supercomputer nodepool capacity for at least one of the listed SKUs per tool, rerun the skill."


