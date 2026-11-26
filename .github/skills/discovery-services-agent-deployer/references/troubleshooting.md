# Troubleshooting

| Symptom | Recovery |
|---|---|
| Missing `pwsh` | Install PowerShell 7+ and rerun. |
| Azure auth failure | Run `az login`, set the correct tenant/subscription, then rerun with `-Resume <RunDir>` when available. |
| Docker unavailable | Use `-BuildMode remote` or omit build mode and let auto select ACR Tasks. |
| ACR push denied | Verify `AcrPush` or equivalent permissions on the registry. |
| Remote build cannot queue | Verify ACR/resource group permissions and Azure CLI connectivity. |
| Tool ARM PUT returns 400 | Check `tool.yaml` schema, `recommended_sku`, image path, and generated `arm-body.json` in the run folder. |
| Tool provisioning does not finish | Rerun with `-Resume <RunDir>`; the deploy stage can continue polling existing in-flight resources. |
| Agent deployment fails | Check the temp `agent.yaml` and `agent-deploy-config.json` in the run folder. |
| Validation times out | Rerun with `-Resume <RunDir>` or deploy with `-SkipValidation` if the user only needs deployment. |
| Validation asks for confirmation | Do not self-approve. Complete pending approvals in Discovery and rerun the validation stage. For a completed confirmation-only reply, collect the user's answer with `ask_user` and pass it as `-ValidationPrompt` in the same run directory. |
| Validation reports no execution evidence | Inspect the saved response snapshot and `validation-result.json`. A plan, an `OK` reply, or an assistant-only success marker is not a tool test. |
| Code executed but receipt validation fails | Check runtime stdout for `DISCOVERY_VALIDATION_RESULT=` with measured checks, tolerances, and nonzero output-file sizes, plus the platform's output-resource URI. Do not fabricate the receipt in assistant text. |

The runner disables Azure CLI telemetry because some CLI versions can emit telemetry cleanup crashes after otherwise successful commands.
