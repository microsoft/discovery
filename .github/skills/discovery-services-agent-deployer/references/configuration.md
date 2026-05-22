# Configuration

Create a local config file by copying:

```powershell
Copy-Item .github/skills/discovery-services-agent-deployer/config.template.json .github/skills/discovery-services-agent-deployer/config.json
```

`config.json` is gitignored because it contains per-user Azure subscription, resource group, registry, tenant, workspace, and project values. Commit only `config.template.json`.

## Fields

| Field | Required | Notes |
|---|---:|---|
| `subscriptionId` | Yes | Azure subscription containing the Discovery project and ACR. |
| `resourceGroup` | Yes | Resource group for `Microsoft.Discovery/tools`. |
| `acrName` | Yes | ACR name without `.azurecr.io`. |
| `acrResourceGroup` | No | ACR resource group when the registry is not in `resourceGroup`; defaults to `resourceGroup`. |
| `location` | Yes | Tool resource region. Ask the user for this value when it is missing; do not infer `uksouth` from the example. |
| `apiVersion` | No | Defaults to `2026-02-01-preview` from `config.template.json`. |
| `workspaceEndpoint` | Yes | Discovery workspace endpoint. |
| `project` | Yes | Discovery project name. |
| `tenantId` | Yes | Entra tenant for Discovery auth. |
| `chatModel` | Yes | Model deployment name replacing `{{CHAT-MODEL}}`. |
| `testPrompt` | No | Optional validation prompt override. When non-empty, validation uses this instead of asking Copilot to generate a prompt. |
| `runReuseWindowMinutes` | No | Recent run folder reuse window. Defaults to `2` and is included in generated config guidance. |
| `forceToolImageRebuild` | Yes | Ask explicitly. `true` rebuilds even when the same ACR repository:tag exists; `false` reuses existing tags. |
| `printAcrLogsOnFailure` | No | Print ACR logs when remote build fails. Defaults to `false` and is included in generated config guidance. |
| `deleteInvestigationAfterTest` | No | Delete validation investigation after test. Defaults to `false` and is included in generated config guidance. |

## Copilot-style input behavior

The runner never assumes `config.json` is present and never uses terminal `Read-Host` prompts for required config. Stage 1 verifies these required values are present: `subscriptionId`, `resourceGroup`, `acrName`, `location`, `workspaceEndpoint`, `project`, `tenantId`, `chatModel`, and `forceToolImageRebuild`. If `config.json` is absent or any required value is missing, Stage 1 prints a structured block:

```text
CONFIG_INPUT_REQUIRED=true
CONFIG_PATH=.github/skills/discovery-services-agent-deployer/config.json
CONFIG_FIELDS_TO_COLLECT=<missing-field-list>
CONFIG_INPUT_FORMAT=copilot
--- COPILOT CONFIG INPUT REQUEST ---
...
--- END COPILOT CONFIG INPUT REQUEST ---
```

When this appears, the assistant should ask the user for the listed values in Copilot chat, create the ignored `config.json` from the response, keep the runner-provided optional defaults in the suggested config shape, and rerun the stage. The assistant must not fill missing required values from examples, defaults, repo history, or personal preference without the user's answer. This is an input-required stop, not a deployment failure: the runner emits `TASK_STATUS=init:input_required`, `[stage-01] STATUS=InputRequired`, and exits with code `2` before Azure deployment work so the user is not left at a hidden terminal prompt.

After Stage 1 succeeds, the runner writes the resolved values into the run-local `prompted-config.json`. Later stages read that run-local file instead of asking again. This keeps one deployment isolated from another and avoids accidental reuse of values from unrelated runs.

`buildMode` and `confirmSupercomputerNodepools` are intentionally not config fields. If Docker is available, the runner asks for build mode as a per-run Copilot choice and should be rerun with `-BuildMode remote` or `-BuildMode local`. Before building, the runner prints the tool image and recommended SKU choices; ask the customer to Proceed or Stop based on Supercomputer nodepool capacity. If they choose Proceed, rerun build with `-ConfirmSupercomputerNodepools`. Do not infer these choices and do not write them to `config.json`. If Docker is unavailable, the runner uses remote ACR build.

Validation prompts are generated at runtime by default. If `testPrompt` is present and non-empty in `config.json`, it acts as a customer-provided override and validation uses it directly. Otherwise, for tool-backed agents, GitHub Copilot should generate a short, concrete validation prompt from the deployed agent/tool context at validation time and pass it with `-ValidationPrompt`.

