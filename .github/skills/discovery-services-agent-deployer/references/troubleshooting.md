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

The runner disables Azure CLI telemetry because some CLI versions can emit telemetry cleanup crashes after otherwise successful commands.
