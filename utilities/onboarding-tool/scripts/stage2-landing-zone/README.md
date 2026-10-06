# Stage 2 — Landing zone (`stage2_prepare.ps1`)

Turns the signed `config.json` into a deployed landing zone (FR2.1–FR2.9): identity, network,
storage, private DNS, plus the quota/exemption and firewall request artifacts. Runs the folded
steps in dependency order and converges on re-run without duplicate or conflicting resources.

## What it does

- RP registration, RBAC role assignments, and the one-time NSP Perimeter Joiner custom role.
- Network provisioning via `network.bicep` (one deployment): VNet, subnets with FR1.2 delegations,
  shared NSG allow-list, UDR route tables, and privatelink DNS zones + links. Builds only when
  `network.model` is byo/byo-spoke/greenfield; byo-existing and managed skip provisioning.
- Private DNS zones + links and BYO storage account/containers with the configured access model.
- Emits the firewall-request artifact and the quota-increase / policy-exemption request bundle
  under `stage2-landing-zone/out/`.
- Stops and surfaces the first hard failure with its remediation.

This stage writes platform resources. Run it against the intended subscription only.

## Prerequisites

- PowerShell 7+ (`pwsh`).
- Azure CLI logged in (`az login`) against the target subscription.
- A green Stage 1 `config.json`.
- Rights to create role assignments (Owner / User Access Administrator / RBAC Administrator at
  the target scope) for the RBAC and NSP-role steps.

## Dependencies

- `../lib/OnboardingCommon.psm1` (imported automatically).
- `network.bicep` (co-located): declarative VNet/subnets/NSG/routes/private-DNS deployed by the
  network step. Deployed directly from the `.bicep`; do not commit a compiled `network.json`.

## Parameters

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json`. |
| `-JsonPath` | no | Write the machine-readable build report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

## Usage

```powershell
./stage2_prepare.ps1 -ConfigPath ./config.json -JsonPath ./out/stage2.json
```

## Output & exit codes

- JSON per-step resource + provisioning state; a human build log; request artifacts in `out/`.
- Idempotent: safe to re-run after fixing a failed step.
- Exit `0` = all steps green; non-zero = at least one failure.

## Spec

`../../script-specs/stage2-landing-zone/stage2_prepare.md`
