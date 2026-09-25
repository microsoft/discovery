# Stage 4 — Deployment (`stage4_deploy.ps1`)

Deploys the Discovery platform in dependency order and turns every failure into an actionable
remediation (FR4.1–FR4.x). Order: supercomputer → workspace → chatModel (gpt-5-4) → project →
bookshelf storage container. All Microsoft.Discovery calls use api-version `2026-06-01`.

## What it does

- Detects true resource state (provisioningState) before each step, so re-runs skip what already
  succeeded and resume from the first incomplete resource.
- Breaks on the first hard failure and prints the mapped remediation via the error-remediation
  engine (`Resolve-DiscoveryError`).
- `-Recovery` re-PUTs a stranded/failed resource to recover a partial deployment.
- Deploys via a Bicep template by default (`discovery-platform.bicep`), with parameters generated
  from the Stage 1 config. Pass `-NoBicep` to use the built-in per-resource ARM PUT sequence, or
  `-BicepPath` / `-ParametersPath` to supply a custom template.

This stage writes platform resources. Run it against the intended subscription only.

## Prerequisites

- PowerShell 7+ (`pwsh`).
- Azure CLI logged in (`az login`) against the target subscription.
- A green Stage 1 `config.json` and a Stage 3 pass.
- `controlPlaneRegion` must equal the region of the BYO VNet holding the managedcluster/nodepool subnets — the supercomputer and its node pool subnet must be co-regional (a mismatch fails with `RegionMismatch`).
- Landing-zone prerequisites in place: resource group, user-assigned identity with the required
  role assignments, storage account + container, and VNet/subnet RBAC.

## Dependencies

- `../lib/OnboardingCommon.psm1` (imported automatically).
- Az CLI with access to Microsoft.Discovery (api-version `2026-06-01`).

## Parameters

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json` (with Stage 4 fields: resourceGroup, managedIdentity, storage). |
| `-Recovery` | no | Re-PUT a failed/stranded resource to recover a partial deployment. |
| `-NoBicep` | no | Use the built-in per-resource ARM PUT sequence instead of the default Bicep deploy. |
| `-BicepPath` / `-ParametersPath` | no | Deploy via a custom Bicep template/params instead of the shipped `discovery-platform.bicep`. |
| `-ReadinessReport` | no | Path to a Stage 3 report to gate on before deploying. |
| `-Subscription` / `-ResourceGroup` / `-Workspace` | no | Override the config-derived targets. |
| `-JsonPath` | no | Write the machine-readable deployment report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

## Usage

```powershell
# Normal deploy (Bicep template, params generated from config)
./stage4_deploy.ps1 -ConfigPath ./config.json -JsonPath ./out/stage4.json

# Deploy via the per-resource ARM PUT sequence instead of Bicep
./stage4_deploy.ps1 -ConfigPath ./config.json -NoBicep -JsonPath ./out/stage4.json

# Recover a partial/failed deployment
./stage4_deploy.ps1 -ConfigPath ./config.json -Recovery -JsonPath ./out/stage4.json
```

## Output & exit codes

- JSON per-resource provisioning state; a human deployment log with remediation on failure.
- Supercomputer creation includes AKS provisioning and can take 15–30 minutes.
- Exit `0` = all resources Succeeded; non-zero = deployment stopped at a failure.

## Spec

`../../script-specs/stage4-deployment/stage4_deploy.md`
