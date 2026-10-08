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
  of its checks/steps; its contract lives in the matching mini-spec under
  [`../script-specs/`](../script-specs/).
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

Per-stage parameters, prerequisites, and dependencies are documented in
[Stage details](#stage-details) below.

## Layout

| Stage | Script | Folded checks / steps |
|---|---|---|
| 1 Planning | [`stage1-planning/stage1_plan.ps1`](stage1-planning/stage1_plan.ps1) | subscription_prereq, capture_fields, subnet_sizing, address_space_conflict, region_availability, quota_sku, naming_validation, policy_preflight, config_export |
| 2 Landing zone | [`stage2-landing-zone/stage2_prepare.ps1`](stage2-landing-zone/stage2_prepare.ps1) | rp_register, rbac_assign, nsp_perimeter_joiner_role, network_provision, nsg_rules, route_tables, private_dns, byo_storage, firewall_request_artifact, quota_exemption_requests |
| 3 Validation | [`stage3-validation/stage3_validate.ps1`](stage3-validation/stage3_validate.ps1) | check_subnet_delegation, check_nsg_effective, check_effective_routes, check_dns_and_pe, testvm_lifecycle, probe_dns, probe_tcp443, probe_https, probe_artifacts, probe_pe_resolution, probe_eastwest, dependency_spec |
| 4 Deployment | [`stage4-deployment/stage4_deploy.ps1`](stage4-deployment/stage4_deploy.ps1) | deploy_order, true_state_detection, error_remediation_engine, recovery_reput |
| 5 Scenario enablement | [`stage5-scenario-enablement/stage5_enable.ps1`](stage5-scenario-enablement/stage5_enable.ps1) | connectivity_check, create_tool, create_agent_bind_tool, create_investigation_conversation, send_prompt_poll, assert_tool_invocation, verification_summary |

Supporting files: `lib/OnboardingCommon.psm1` (shared module), two planning forms —
`stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx` (tool provisions the VNet) and
`stage1-planning/discovery-resource-planning-form-byo-vnet.xlsx` (you bring an existing VNet) —
`stage3-validation/dependency-spec.json` (per-profile check set, FR3.8),
`examples/sample-config.json` (a filled reference config).

## Usage

Run every command from this `scripts/` directory (the paths below are relative to it). First pick
the planning form that matches your network model and fill in its yellow Value cells:

- **Managed VNet** (the tool provisions the VNet): `stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx`
- **BYO existing VNet** (you pre-created the VNet; Stage 3 validates it): `stage1-planning/discovery-resource-planning-form-byo-vnet.xlsx`

The `./out/` directory is created automatically, and Stage 1 only writes `config.json` once it
reaches a `GO` verdict — Stages 2–5 consume that file, so resolve any failing Stage 1 checks (or add
a `WAIVER` row) before continuing. Deny/audit policies are collected live from the subscription at
runtime; add a `POLICY` row only to declare or override one.

```powershell
cd utilities/onboarding-tool/scripts   # all commands are relative to this directory

# Stage 1 — validate the planning form and emit the ground-truth config.
# (swap in discovery-resource-planning-form-byo-vnet.xlsx for the BYO-VNet path)
./stage1-planning/stage1_plan.ps1 -FormPath ./stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx -OutConfig ./config.json -JsonPath ./out/stage1.json

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

## Stage details

Full per-stage parameters, prerequisites, and dependencies. Every stage imports
[`lib/OnboardingCommon.psm1`](lib/OnboardingCommon.psm1) automatically and takes `-JsonPath` and
`-PassThru`.

### Stage 1 — Planning (`stage1-planning/stage1_plan.ps1`)

Parses the filled network-planning form (`discovery-resource-planning-form-managed-vnet.xlsx` or
`discovery-resource-planning-form-byo-vnet.xlsx`, `Config` sheet, or a `.json` config for testing), runs every
embedded planning validation (FR1.0–FR1.8), and emits
`config.json` — the single source of truth for Stages 2–5. The config is written only when all P0
checks pass or carry a recorded waiver. Az-dependent checks degrade to Warn/Skip when not logged
in, so the parser and local checks run offline. `.xlsx` forms are read natively (zip + XML); no
`ImportExcel` module required.

| Parameter | Required | Description |
|---|---|---|
| `-FormPath` | yes | Filled planning form (`.xlsx` or `.json`). |
| `-OutConfig` | no | Path to write the validated `config.json`. |
| `-JsonPath` | no | Write the machine-readable check report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

### Stage 2 — Landing zone (`stage2-landing-zone/stage2_prepare.ps1`)

Turns the signed `config.json` into a deployed landing zone (FR2.1–FR2.9): RP registration, RBAC,
the one-time NSP Perimeter Joiner custom role, network provisioning via `network.bicep` (VNet,
subnets with FR1.2 delegations, shared NSG allow-list, UDR route tables, privatelink DNS zones +
links), BYO storage, and the firewall-request / quota-exemption artifacts under `out/`. Builds the
network only when `network.model` is byo/byo-spoke/greenfield; byo-existing and managed skip
provisioning. Idempotent; stops on the first hard failure with its remediation. **Writes platform
resources — run against the intended subscription only.** Requires rights to create role
assignments (Owner / User Access Administrator / RBAC Administrator at the target scope).

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json`. |
| `-JsonPath` | no | Write the machine-readable build report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

### Stage 3 — Validation (`stage3-validation/stage3_validate.ps1`)

Read-only readiness gate before deployment (FR3.1–FR3.8). Runs control-plane checks (subnet
delegation, effective NSG rules, effective routes, DNS + private-endpoint resolution) and, with
`-WithVm`, in-network probes from an ephemeral test VM (always torn down). The check set is driven
per profile by `dependency-spec.json` (in this folder). Requires a green Stage 1 `config.json` and
a provisioned landing zone (Stage 2); for `-WithVm`, rights to create/delete a VM in the target
subnet.

> Note: `-WithVm` in-network probing is temporarily skipped (see [TODO / known gaps](#todo--known-gaps)).
> Run Stage 3 without `-WithVm` and rely on the control-plane checks until VM-based validation is
> re-enabled.

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json`. |
| `-Profile` | no | `supercomputer` (default), `workspace`, or `bookshelf`. |
| `-WithVm` | no | Add the ephemeral probe VM and run in-network probes. |
| `-JsonPath` | no | Write the machine-readable check report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

### Stage 4 — Deployment (`stage4-deployment/stage4_deploy.ps1`)

Deploys the Discovery platform in dependency order (supercomputer → workspace → chatModel →
project → bookshelf storage container; Microsoft.Discovery api-version `2026-06-01`) and turns
every failure into an actionable remediation (`Resolve-DiscoveryError`). Detects true resource
state before each step so re-runs resume from the first incomplete resource. Deploys via
`discovery-platform.bicep` by default (params generated from the Stage 1 config); `-NoBicep` uses
the built-in per-resource ARM PUT sequence, `-Recovery` re-PUTs a stranded resource.
`controlPlaneRegion` must equal the region of the BYO VNet holding the managedcluster/nodepool
subnets. Supercomputer creation includes AKS provisioning and can take 15–30 minutes. **Writes
platform resources — run against the intended subscription only.**

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

### Stage 5 — Scenario enablement (`stage5-scenario-enablement/stage5_enable.ps1`)

End-to-end certification with the hero use case (FR5.1). Verifies platform private-endpoint DNS
and 443 reachability, creates a tool, binds it to an agent, opens an investigation + conversation,
sends a prompt, and asserts the tool was actually invoked (passes only on a real tool invocation,
not just an HTTP 200). Requires a green Stage 1 `config.json`, a successful Stage 4 deployment
(workspace + project + chatModel live), and a network path to the platform private endpoint (run
inside the VNet or a peered/allowed network).

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json`. |
| `-ResourceGroup` / `-Workspace` / `-Project` | no | Override the config-derived targets. |
| `-ChatModel` | no | Chat model deployment to use (defaults to the deployed one). |
| `-ToolArmId` | no | Reuse an existing tool ARM id instead of creating one. |
| `-Prompt` | no | Override the hero-use-case prompt. |
| `-JsonPath` | no | Write the machine-readable certification report here. |

## TODO / known gaps

Tracked work not yet implemented in the scripts:

- Stage 3 — test VM connectivity harness (`-WithVm`). The ephemeral probe VM and its in-network
  probes (DNS, TCP 443, HTTPS/artifact, PE resolution, east-west 10250) plus the NIC-derived
  effective-NSG/route lookups are temporarily disabled; `az vm create` trips an empty-arg binding
  issue (`--public-ip-address ''` / `--nsg ''`). Re-enable once that call is fixed; until then
  run Stage 3 without `-WithVm` and rely on the control-plane checks.
- Stage 4 — bookshelf content. Stage 4 creates the bookshelf storage container
  (`Microsoft.Discovery/storageContainers`) but does not create or ingest the storage asset
  (`names.storageAsset`). Add asset creation / knowledge-base content load.
- Stage 5 — scenario validation. Stage 5 asserts a real tool invocation and checks the bookshelf
  private endpoints, but does not validate end-to-end bookshelf retrieval (that the ingested asset
  is queryable by the agent). Add that retrieval assertion.

## FR traceability

Each script header names its FR mapping and its spec file. Read a stage's requirements and
acceptance criteria in [`../Onboarding-Tooling-Requirements.md`](../Onboarding-Tooling-Requirements.md),
then the per-script spec in [`../script-specs/`](../script-specs/) for the contract.
