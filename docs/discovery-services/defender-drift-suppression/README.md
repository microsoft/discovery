# Suppress Defender for Containers binary-drift alerts for interactive debugging

Microsoft Discovery runs your tools and jobs as containers on Azure Kubernetes
Service. If you enable [Microsoft Defender for
Containers](https://learn.microsoft.com/azure/defender-for-cloud/defender-for-containers-introduction)
on the subscription that hosts your Discovery compute, using the **interactive
container debugging** feature — which opens a VS Code tunnel into a running
tool container — produces expected **binary drift** alerts:

> **A drift binary detected executing in the container**
> (`alertType K8S.NODE_DriftDetection`)

This is expected and benign. To attach a debugger, Discovery downloads the
[VS Code CLI](https://code.visualstudio.com/docs/remote/tunnels) into the
container **at runtime** and runs it (plus the VS Code server it fetches on
first connect). [Binary drift
detection](https://learn.microsoft.com/azure/defender-for-cloud/binary-drift-detection)
flags any process started from a binary that wasn't part of the original
container image, so these runtime-fetched binaries trip the alert.

The artifacts in this folder create two Defender **alert-suppression rules**
that dismiss exactly those alerts, scoped by the debug process command line so
your other workloads are unaffected:

| Rule | Matches process command line contains | Covers |
|------|----------------------------------------|--------|
| `Binary-drift-vscode-cli-download` | `vscode-cli.tar.gz` | VS Code CLI download + `tar` extract |
| `Binary-drift-vscode-cli-tunnel`   | `/tmp/_debug_c`     | VS Code CLI + server tunnel processes |

Both are created `Enabled` with reason `SpecificEntityFalsePositive`.

## Prerequisites
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), signed
  in (`az login`) to the tenant that owns the subscription.
- **Security Admin** (or Owner) on the target subscription.

## Apply

Pick **one** of the following. All are idempotent (safe to re-run).

### Option A — ARM template (no extra tooling)
```bash
az deployment sub create \
  --location <region> \
  --template-file defender-drift-suppression.json
```

### Option B — Bicep
```bash
az deployment sub create \
  --location <region> \
  --template-file defender-drift-suppression.bicep
```

### Option C — script
```bash
# Linux/macOS
./set-drift-suppression.sh [SUBSCRIPTION_ID] [Enabled|Disabled]
```
```powershell
# Windows
./set-drift-suppression.ps1 -SubscriptionId <sub> -State Enabled
```
`SUBSCRIPTION_ID` / `-SubscriptionId` default to the current `az account` subscription.

## Verify
```bash
az rest --method get \
  --url "https://management.azure.com/subscriptions/<sub>/providers/Microsoft.Security/alertsSuppressionRules?api-version=2019-01-01-preview" \
  --query "value[].{name:name, state:properties.state, contains:properties.suppressionAlertsScope.allOf[0].contains}" -o table
```

## Remove
```bash
az rest --method delete --url "https://management.azure.com/subscriptions/<sub>/providers/Microsoft.Security/alertsSuppressionRules/Binary-drift-vscode-cli-download?api-version=2019-01-01-preview"
az rest --method delete --url "https://management.azure.com/subscriptions/<sub>/providers/Microsoft.Security/alertsSuppressionRules/Binary-drift-vscode-cli-tunnel?api-version=2019-01-01-preview"
```

## Notes
- Rules are **subscription-scoped**; apply once per subscription that hosts a
  Discovery compute cluster with Defender for Containers enabled.
- Suppression rules only dismiss the interactive-debug drift alerts described
  above. Drift from any other unexpected process is still reported.
- The `comment` field on these rules is capped at **140 characters** by the API
  (longer values return an opaque HTTP 500).
- Changes propagate to the Defender sensors within ~30 minutes.

## Learn more
- [Binary drift detection](https://learn.microsoft.com/azure/defender-for-cloud/binary-drift-detection)
- [Suppress alerts from Microsoft Defender for Cloud](https://learn.microsoft.com/azure/defender-for-cloud/alerts-suppression-rules)
- [Microsoft Discovery documentation](https://learn.microsoft.com/azure/microsoft-discovery/)
