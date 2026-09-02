#!/usr/bin/env bash
# Create/update the Microsoft Discovery interactive-debug (VS Code tunnel) binary-drift
# suppression rules in Microsoft Defender for Cloud. Idempotent (safe to re-run).
#
#   ./set-drift-suppression.sh [SUBSCRIPTION_ID] [STATE]
#
# SUBSCRIPTION_ID  Target subscription (default: current `az account` sub).
# STATE            Enabled | Disabled (default: Enabled).
#
# Requires: Azure CLI, and Security Admin (or Owner) on the subscription.
set -euo pipefail

SUB="${1:-$(az account show --query id -o tsv | tr -d '\r\n')}"
STATE="${2:-Enabled}"
API="2019-01-01-preview"

put_rule() {
  local name="$1" value="$2" comment="$3"
  local body
  body=$(cat <<JSON
{
  "properties": {
    "alertType": "K8S.NODE_DriftDetection",
    "reason": "SpecificEntityFalsePositive",
    "state": "${STATE}",
    "comment": "${comment}",
    "suppressionAlertsScope": {
      "allOf": [
        { "field": "entities.process.commandline", "contains": "${value}" }
      ]
    }
  }
}
JSON
)
  echo "==> ${name}  (commandline contains '${value}')"
  # The Defender alertsSuppressionRules API occasionally returns a transient 500;
  # retry a few times before giving up.
  local attempt=0
  until az rest --method put \
    --url "https://management.azure.com/subscriptions/${SUB}/providers/Microsoft.Security/alertsSuppressionRules/${name}?api-version=${API}" \
    --headers "Content-Type=application/json" \
    --body "${body}" \
    --query "{name:name, state:properties.state, field:properties.suppressionAlertsScope.allOf[0].field, contains:properties.suppressionAlertsScope.allOf[0].contains}" \
    -o table
  do
    attempt=$((attempt + 1))
    if [ "${attempt}" -ge 5 ]; then echo "Failed to set ${name} after ${attempt} attempts." >&2; return 1; fi
    echo "   transient error (attempt ${attempt}), retrying in 5s..." >&2
    sleep 5
  done
}

echo "Subscription: ${SUB}"
echo "State:        ${STATE}"
echo

put_rule "Binary-drift-vscode-cli-download" "vscode-cli.tar.gz" \
  "Discovery interactive debug (VS Code tunnel): CLI download + tar extract of vscode-cli.tar.gz. Runtime tools are not in the image."

put_rule "Binary-drift-vscode-cli-tunnel" "/tmp/_debug_c" \
  "Discovery interactive debug (VS Code tunnel): CLI/server exec from /tmp/_debug_*. Runtime-fetched binaries are not in the image."

echo
echo "Done. Both rules are now present on subscription ${SUB}."
