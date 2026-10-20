# Microsoft Discovery onboarding scripts

PowerShell 7 and Azure CLI implementation of the five-stage Microsoft Discovery customer
onboarding flow.

This file is a **maintainer index**, not a customer runbook. Use the document that matches your
task:

| Audience / task | Source of truth |
|---|---|
| Customer preparing or running onboarding | [User guide](USER-GUIDE.md) |
| Product behavior, priorities and acceptance criteria | [Tooling requirements](../Onboarding-Tooling-Requirements.md) |
| Script contracts and FR mappings | [Per-stage specifications](../script-specs/) |
| Generated configuration contract | [Config schema](../script-specs/config.schema.json) |
| Regression coverage | [Pester tests](../tests/) |

Do not duplicate customer prerequisites, permissions, commands or troubleshooting here. Those
belong in the user guide. Do not duplicate functional requirements here; those belong in the
requirements specification.

## Implementation map

| Stage | Script | Contract | Responsibility |
|---|---|---|---|
| 1 — Planning | [stage1_plan.ps1](stage1-planning/stage1_plan.ps1) | [Stage 1 spec](../script-specs/stage1-planning/stage1_plan.md) | Validate the planning form and emit `config.json`. |
| 2 — Landing zone | [stage2_prepare.ps1](stage2-landing-zone/stage2_prepare.ps1) | [Stage 2 spec](../script-specs/stage2-landing-zone/stage2_prepare.md) | Register providers, prepare RBAC, network and storage, and emit customer-action artifacts. |
| 3 — Validation | [stage3_validate.ps1](stage3-validation/stage3_validate.ps1) | [Stage 3 spec](../script-specs/stage3-validation/stage3_validate.md) | Gate deployment with profile-specific readiness checks. |
| 4 — Deployment | [stage4_deploy.ps1](stage4-deployment/stage4_deploy.ps1) | [Stage 4 spec](../script-specs/stage4-deployment/stage4_deploy.md) | Deploy and recover the Discovery platform in dependency order. |
| 5 — Scenario enablement | [stage5_enable.ps1](stage5-scenario-enablement/stage5_enable.ps1) | [Stage 5 spec](../script-specs/stage5-scenario-enablement/stage5_enable.md) | Create and verify the Q&A certification scenario. |

Supporting implementation:

- [OnboardingCommon.psm1](lib/OnboardingCommon.psm1) — configuration, Azure CLI, reporting,
  quota, CIDR and PIM helpers.
- [dependency-spec.json](stage3-validation/dependency-spec.json) — Stage 3 profile/check mapping.
- [Managed VNet planning form](stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx)
  and [BYO VNet planning form](stage1-planning/discovery-resource-planning-form-byo-vnet.xlsx).
- [Examples](examples/) — illustrative inputs and historical outputs; customers should generate
  a fresh config and reports.

## Implementation conventions

- Stage 1 emits the single `config.json`; Stages 2–5 consume it.
- Each stage stops on its first hard failure and exits non-zero on a `NO-GO` verdict.
- `-JsonPath` produces machine-readable JSON and a sibling Markdown report.
- `-PassThru` returns result objects for tests and composition.
- Stage 2 and Stage 4 write persistent Azure resources. Stage 3 is read-only unless `-WithVm` is
  explicitly used.
- Shared logic belongs in `lib/OnboardingCommon.psm1`; stage-specific orchestration stays in the
  stage script.
- Update the requirements, matching stage spec, user guide and tests when behavior changes.

## Validation

The Pester suites are:

- [OnboardingCommon.Tests.ps1](../tests/OnboardingCommon.Tests.ps1)
- [CommonContracts.Tests.ps1](../tests/CommonContracts.Tests.ps1)
- [DeploymentRegression.Tests.ps1](../tests/DeploymentRegression.Tests.ps1)
- [NspRole.Tests.ps1](../tests/NspRole.Tests.ps1)
- [Stage1Policy.Tests.ps1](../tests/Stage1Policy.Tests.ps1)
- [Stage1Config.Tests.ps1](../tests/Stage1Config.Tests.ps1)
- [Stage2Orchestration.Tests.ps1](../tests/Stage2Orchestration.Tests.ps1)
- [Stage2Storage.Tests.ps1](../tests/Stage2Storage.Tests.ps1)
- [Stage3Network.Tests.ps1](../tests/Stage3Network.Tests.ps1)
- [Stage4State.Tests.ps1](../tests/Stage4State.Tests.ps1)
- [Stage5Workflow.Tests.ps1](../tests/Stage5Workflow.Tests.ps1)
- [RbacModes.Tests.ps1](../tests/RbacModes.Tests.ps1)

Run the applicable suites from `utilities/onboarding-tool` with PowerShell 7. Also run PowerShell
parser checks, JSON/schema validation where relevant, workbook structural checks after editing
planning forms, and `git diff --check`.
