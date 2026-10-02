# Stage 1 — Planning (`stage1_plan.ps1`)

Parses the customer's filled network-planning form, runs every embedded planning validation
(FR1.0–FR1.8), and emits `config.json` — the single source of truth consumed by Stages 2–5.
The config is written only when all P0 checks pass or carry a recorded waiver.

## What it does

- Reads the planning spreadsheet (`network-planning-form-template.xlsx`, `Config` sheet) or a
  `.json` config for testing, and normalizes it into the config model (`config.schema.json`).
- Validates, in one pass: subscription prerequisites, field capture, subnet sizing +
  delegation, address-space conflicts, region availability/capacity, quota/SKU/TPM/Cosmos,
  naming rules + availability, policy pre-flight, and the export gate.
- Az-dependent checks (subscription enablement, SKU-in-region, workspace name availability)
  degrade to Warn/Skip when not logged in, so the parser and local checks run offline.

## Prerequisites

- PowerShell 7+ (`pwsh`).
- Azure CLI logged in (`az login`) for the online checks — optional; skipped when absent.
- A filled planning form (`.xlsx` or `.json`).

## Dependencies

- `../lib/OnboardingCommon.psm1` (imported automatically).
- `.xlsx` forms are read natively (zip + XML); no `ImportExcel` module required.

## Parameters

| Parameter | Required | Description |
|---|---|---|
| `-FormPath` | yes | Filled planning form (`.xlsx` or `.json`). |
| `-OutConfig` | no | Path to write the validated `config.json`. |
| `-JsonPath` | no | Write the machine-readable check report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

## Deliverables in this folder

- `stage1_plan.ps1` — the planner.
- `network-planning-form-template.xlsx` — the blank planning form shared with the customer to fill in (`Config` sheet).

## Usage

```powershell
./stage1_plan.ps1 -FormPath ./network-planning-form-template.xlsx -OutConfig ./config.json -JsonPath ./out/stage1.json
```

## Output & exit codes

- JSON check report plus a human go/no-go table (each row: check, status, remediation).
- `config.json` when all P0 checks pass or are waived.
- Exit `0` = all green; non-zero = at least one failure (export blocked).

## Spec

`../../script-specs/stage1-planning/stage1_plan.md`
