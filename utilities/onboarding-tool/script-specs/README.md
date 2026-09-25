# Onboarding tooling — script specs

One consolidated spec per onboarding stage. Each stage is a single PowerShell 7 + Az CLI script,
and each has exactly one spec file here that describes its contract and folds in every check/step
it performs. Specs only — no implementation. Every spec maps to the FR ids in
`../Onboarding-Tooling-Requirements.md`, which stays the authoritative requirements source.

## Conventions

- One stage, one script, one spec. Each spec documents the consolidated script and lists the
  folded checks/steps with their FR ids and remediation.
- Language: PowerShell 7 (`pwsh`) + Azure CLI (`az`).
- Config flows forward. Stage 1 emits `config.json` (see `config.schema.json`); Stages 2–5
  consume it and never re-ask for what Stage 1 captured.
- Every script emits JSON for automation and a human-readable report, and exits non-zero on
  any failure so it can gate a pipeline.
- Every failure returns the exact remediation, not just a red mark.
- Read-only stays read-only. Only Stage 2 and Stage 4 write platform resources; Stage 3
  writes only its ephemeral test VM.

## Layout

| Stage | Script | Spec | Folded checks / steps |
|---|---|---|---|
| 1 Planning | `stage1-planning/stage1_plan.ps1` | [`stage1-planning/stage1_plan.md`](stage1-planning/stage1_plan.md) | subscription_prereq, capture_fields, subnet_sizing, address_space_conflict, region_availability, quota_sku, naming_validation, policy_preflight, config_export |
| 2 Landing zone | `stage2-landing-zone/stage2_prepare.ps1` | [`stage2-landing-zone/stage2_prepare.md`](stage2-landing-zone/stage2_prepare.md) | rp_register, rbac_assign, nsp_perimeter_joiner_role, network_provision, nsg_rules, route_tables, private_dns, byo_storage, firewall_request_artifact, quota_exemption_requests |
| 3 Validation | `stage3-validation/stage3_validate.ps1` | [`stage3-validation/stage3_validate.md`](stage3-validation/stage3_validate.md) | check_subnet_delegation, check_nsg_effective, check_effective_routes, check_dns_and_pe, testvm_lifecycle, probe_dns, probe_tcp443, probe_https, probe_artifacts, probe_pe_resolution, probe_eastwest, dependency_spec |
| 4 Deployment | `stage4-deployment/stage4_deploy.ps1` | [`stage4-deployment/stage4_deploy.md`](stage4-deployment/stage4_deploy.md) | deploy_order, true_state_detection, error_remediation_engine, recovery_reput |
| 5 Certification | `stage5-certification/stage5_certify.ps1` | [`stage5-certification/stage5_certify.md`](stage5-certification/stage5_certify.md) | connectivity_check, create_tool, create_agent_bind_tool, create_investigation_conversation, send_prompt_poll, assert_tool_invocation, verification_summary |

Data files: `config.schema.json` (the Stage 1 config model),
`../scripts/stage3-validation/dependency-spec.json` (per-profile check set, FR3.8).

## FR traceability

Each spec's header names its FR mapping. Read a stage's requirements and acceptance criteria
in `../Onboarding-Tooling-Requirements.md`, then the per-stage spec here for the contract, and
the matching `../scripts/stageN-*/README.md` for how to run the script.
