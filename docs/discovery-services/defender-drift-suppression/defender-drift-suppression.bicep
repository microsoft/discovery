// Defender for Cloud – binary-drift alert suppression rules for Microsoft
// Discovery interactive container debugging (VS Code tunnel).
//
// To attach a debugger, Discovery downloads the VS Code CLI into the target
// container at runtime, extracts it with `tar`, and runs the CLI + the VS Code
// server it fetches on first connect. Those runtime-fetched binaries are not
// part of the container image, so Microsoft Defender for Containers raises
// "binary drift" alerts (alertType K8S.NODE_DriftDetection). These two rules
// dismiss exactly those alerts, scoped by process command line so unrelated
// workloads are unaffected.
//
// Deploy against the subscription that hosts your Discovery compute:
//   az deployment sub create \
//     --location <region> \
//     --template-file defender-drift-suppression.bicep
//
// Idempotent: re-running updates the rules in place.

targetScope = 'subscription'

@description('Enable or disable both suppression rules.')
param ruleState string = 'Enabled'

resource downloadRule 'Microsoft.Security/alertsSuppressionRules@2019-01-01-preview' = {
  name: 'Binary-drift-vscode-cli-download'
  properties: {
    alertType: 'K8S.NODE_DriftDetection'
    reason: 'SpecificEntityFalsePositive'
    state: ruleState
    comment: 'Discovery interactive debug (VS Code tunnel): CLI download + tar extract of vscode-cli.tar.gz. Runtime tools are not in the image.'
    suppressionAlertsScope: {
      allOf: [
        {
          field: 'entities.process.commandline'
          contains: 'vscode-cli.tar.gz'
        }
      ]
    }
  }
}

resource tunnelRule 'Microsoft.Security/alertsSuppressionRules@2019-01-01-preview' = {
  name: 'Binary-drift-vscode-cli-tunnel'
  properties: {
    alertType: 'K8S.NODE_DriftDetection'
    reason: 'SpecificEntityFalsePositive'
    state: ruleState
    comment: 'Discovery interactive debug (VS Code tunnel): CLI/server exec from /tmp/_debug_*. Runtime-fetched binaries are not in the image.'
    suppressionAlertsScope: {
      allOf: [
        {
          field: 'entities.process.commandline'
          contains: '/tmp/_debug_c'
        }
      ]
    }
  }
}
