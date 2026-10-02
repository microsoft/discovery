# Stage 3 — Validation (`stage3_validate.ps1`)

Read-only readiness gate before deployment (FR3.1–FR3.8). Runs control-plane checks (subnet
delegation, effective NSG rules, effective routes, DNS + private-endpoint resolution) and, with
`-WithVm`, in-network probes from an ephemeral test VM (DNS, TCP 443, HTTPS/artifact, PE
resolution, east-west 10250). The check set is driven per profile by `dependency-spec.json`.

## What it does

- Resolves the required check set for the chosen profile from `dependency-spec.json` (FR3.8).
- Control-plane, read-only: subnet delegation, effective NSG, effective routes, DNS/PE.
- With `-WithVm`: provisions one disposable probe VM, runs the connectivity probes, then tears
  it down unconditionally (the only resource this stage writes).
- Every failure carries an exact remediation (e.g. NSG egress, UDR black-hole, DNS zone link,
  managed-cluster route → VnetLocal).

## Prerequisites

- PowerShell 7+ (`pwsh`).
- Azure CLI logged in (`az login`) against the target subscription.
- A green Stage 1 `config.json` and a provisioned landing zone (Stage 2).
- For `-WithVm`: rights to create/delete a VM in the target subnet.

## Dependencies

- `../lib/OnboardingCommon.psm1` (imported automatically).
- `dependency-spec.json` (in this folder) — per-profile required-check set.

## Parameters

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json`. |
| `-Profile` | no | `supercomputer` (default), `workspace`, or `bookshelf`. |
| `-WithVm` | no | Add the ephemeral probe VM and run in-network probes. |
| `-JsonPath` | no | Write the machine-readable check report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

## Usage

```powershell
./stage3_validate.ps1 -ConfigPath ./config.json -Profile workspace -WithVm -JsonPath ./out/stage3.json
```

## Output & exit codes

- JSON check report plus a human readiness table; the probe VM is always removed.
- Exit `0` = ready to deploy; non-zero = at least one blocking check failed.

## Spec

`../../script-specs/stage3-validation/stage3_validate.md`
