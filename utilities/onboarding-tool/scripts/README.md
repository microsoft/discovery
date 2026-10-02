# Onboarding tooling — PowerShell scripts

Working PowerShell (Az CLI) implementation of the onboarding tooling. Each script implements
the contract in the matching mini-spec under [`../script-specs/`](../script-specs/), which
maps back to the FR ids in [`../Onboarding-Tooling-Requirements.md`](../Onboarding-Tooling-Requirements.md).
The requirements doc stays authoritative; these scripts are the implementation.

## Requirements

- PowerShell 7+ (`pwsh`). Every script declares `#Requires -Version 7.0`.
- Azure CLI (`az`) logged in (`az login`) with access to the target subscription.
- Optional: the `ImportExcel` module, only if you feed Stage 1 an `.xlsx` planning form
  instead of JSON (`Install-Module ImportExcel -Scope CurrentUser`).

## Conventions

- One stage, one script, one spec. Each stage is a single consolidated script that folds in all
  of its checks/steps; each has a matching per-script `README.md` in its folder.
- Config flows forward. Stage 1 emits `config.json` (see
  [`../script-specs/config.schema.json`](../script-specs/config.schema.json)); Stages 2–5
  consume it and never re-ask for what Stage 1 captured.
- Every script emits JSON (`-JsonPath`) and a human-readable report, and exits non-zero on any
  failure so it can gate a pipeline.
- Every failure carries an exact remediation string, not just a red mark.
- Read-only stays read-only: only Stage 2 and Stage 4 write platform resources; Stage 3 writes
  only its ephemeral test VM.
- Shared behavior (config load, `az` wrapper, result model, report + exit, CIDR math) lives in
  [`lib/OnboardingCommon.psm1`](lib/OnboardingCommon.psm1); every script imports it.

## Common parameters

All stage scripts take:

- `-ConfigPath <config.json>` — the config (Stage 1 reads its planning form via `-FormPath`).
- `-JsonPath <path>` — optional; write the machine report here.
- `-PassThru` — return the raw result objects instead of printing a report and exiting.

Each stage folder has a `README.md` with that script's full parameter list, prerequisites, and
dependencies.

## Layout

| Stage | Script | Folded checks / steps |
|---|---|---|
| 1 Planning | [`stage1-planning/stage1_plan.ps1`](stage1-planning/README.md) | subscription_prereq, capture_fields, subnet_sizing, address_space_conflict, region_availability, quota_sku, naming_validation, policy_preflight, config_export |
| 2 Landing zone | [`stage2-landing-zone/stage2_prepare.ps1`](stage2-landing-zone/README.md) | rp_register, rbac_assign, nsp_perimeter_joiner_role, network_provision, nsg_rules, route_tables, private_dns, byo_storage, firewall_request_artifact, quota_exemption_requests |
| 3 Validation | [`stage3-validation/stage3_validate.ps1`](stage3-validation/README.md) | check_subnet_delegation, check_nsg_effective, check_effective_routes, check_dns_and_pe, testvm_lifecycle, probe_dns, probe_tcp443, probe_https, probe_artifacts, probe_pe_resolution, probe_eastwest, dependency_spec |
| 4 Deployment | [`stage4-deployment/stage4_deploy.ps1`](stage4-deployment/README.md) | deploy_order, true_state_detection, error_remediation_engine, recovery_reput |
| 5 Scenario enablement | [`stage5-scenario-enablement/stage5_enable.ps1`](stage5-scenario-enablement/README.md) | connectivity_check, create_tool, create_agent_bind_tool, create_investigation_conversation, send_prompt_poll, assert_tool_invocation, verification_summary |

Supporting files: `lib/OnboardingCommon.psm1` (shared module),
`stage1-planning/network-planning-form-template.xlsx` (blank planning form for the customer),
`stage3-validation/dependency-spec.json` (per-profile check set, FR3.8),
`examples/sample-config.json` (a filled reference config).

## Usage

```powershell
# Stage 1 — validate the planning form and emit the ground-truth config.
./stage1-planning/stage1_plan.ps1 -FormPath ./my-plan.json -OutConfig ./config.json -JsonPath ./out/stage1.json

# Stage 2 — prepare the landing zone (writes resources, idempotent).
./stage2-landing-zone/stage2_prepare.ps1 -ConfigPath ./config.json -JsonPath ./out/stage2.json

# Stage 3 — validate readiness (read-only; -WithVm adds the disposable connectivity test VM).
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile workspace -WithVm -JsonPath ./out/stage3.json

# Stage 4 — deploy the platform in dependency order with error-to-remediation.
./stage4-deployment/stage4_deploy.ps1 -ConfigPath ./config.json -JsonPath ./out/stage4.json

# Stage 5 — scenario enablement with the hero use case (fails unless a tool is really invoked).
./stage5-scenario-enablement/stage5_enable.ps1 -ConfigPath ./config.json -JsonPath ./out/stage5.json
```

Each command exits `0` only when every check passed (or was waived); non-zero otherwise, so the
stages chain in a pipeline.

## FR traceability

Each script header names its FR mapping and its spec file. Read a stage's requirements and
acceptance criteria in [`../Onboarding-Tooling-Requirements.md`](../Onboarding-Tooling-Requirements.md),
then the per-script spec in [`../script-specs/`](../script-specs/) for the contract.
