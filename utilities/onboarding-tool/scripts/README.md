# Onboarding tooling — PowerShell scripts

Working PowerShell (Az CLI) implementation of the onboarding tooling. Each script implements
the contract in the matching mini-spec under [`../script-specs/`](../script-specs/), which
maps back to the FR ids in [`../Onboarding-Tooling-Requirements.md`](../Onboarding-Tooling-Requirements.md).
The requirements doc stays authoritative; these scripts are the implementation.

## Requirements

- PowerShell 7+ (`pwsh`). Every script declares `#Requires -Version 7.0`.
- Azure CLI (`az`) logged in (`az login`) with access to the target subscription.
- No `ImportExcel` module is required; Stage 1 reads `.xlsx` planning forms natively.

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
| 2 Landing zone | [`stage2-landing-zone/stage2_prepare.ps1`](stage2-landing-zone/stage2_prepare.ps1) | rp_register, rbac_assign, nsp_perimeter_joiner_role, network_provision, nsg_rules, route_tables, private_dns, byo_storage, managed_identity_roles, firewall_request_artifact, quota_exemption_requests |
| 3 Validation | [`stage3-validation/stage3_validate.ps1`](stage3-validation/stage3_validate.ps1) | check_subnet_delegation, check_nsg_effective, check_effective_routes, check_dns_and_pe, check_quota, testvm_lifecycle, probe_dns, probe_tcp443, probe_https, probe_artifacts, probe_pe_resolution, probe_eastwest, dependency_spec |
| 4 Deployment | [`stage4-deployment/stage4_deploy.ps1`](stage4-deployment/stage4_deploy.ps1) | deploy_order, true_state_detection, error_remediation_engine, recovery_reput |
| 5 Scenario enablement | [`stage5-scenario-enablement/stage5_enable.ps1`](stage5-scenario-enablement/stage5_enable.ps1) | create_agent, create_investigation_conversation, send_prompt_poll, verify_response, verification_summary |

Supporting files: `lib/OnboardingCommon.psm1` (shared module), two planning forms —
[`discovery-resource-planning-form-managed-vnet.xlsx`](stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx) (tool-provisioned network) and
[`discovery-resource-planning-form-byo-vnet.xlsx`](stage1-planning/discovery-resource-planning-form-byo-vnet.xlsx) (customer-defined provisioning or existing-network validation) —
`stage3-validation/dependency-spec.json` (per-profile check set, FR3.8),
`examples/sample-config.json` (a filled reference config).

## Usage

Run every command from this `scripts/` directory (the paths below are relative to it). First pick
the planning form that matches your network model and fill in its yellow Value cells:

- **Managed worksheet:** use it for a new, dedicated Discovery network provisioned by the tool.
  Its `network.model` dropdown contains only `managed`.
- **BYO worksheet:** use it for an existing customer-prepared network, a customer-defined network
  the tool should provision, or a Discovery spoke for an enterprise hub. Its dropdown contains
  `byo`, `byo-spoke`, and `byo-existing`.

| Worksheet | `network.model` | When to select it | Network provisioning in Stage 2 |
|---|---|---|---|
| Managed | `managed` | Let the tool provision the Discovery network layout using your settings. | Deploys the VNet, subnets, shared NSG, route tables when UDR is selected, and private DNS. |
| BYO | `byo` | Supply your own network layout and let the tool provision it. | Same provisioning template as `managed`; not validation-only. |
| BYO | `byo-spoke` | Provision a Discovery spoke intended to connect to your enterprise hub. | Same provisioning template; customer must arrange hub connectivity and firewall/NVA egress separately. |
| BYO | `byo-existing` | Use an existing VNet and Discovery subnets prepared by your network team. | Skips VNet/network-template provisioning; Stage 1 checks existing resources and Stage 3 validates networking. Other Stage 2 steps still run. |

**The selected value, not the filename, controls behavior.** Check `network.model` before
running Stage 1, especially in a previously filled copy. `managed`, `byo`, and `byo-spoke` can
modify an existing VNet: the template declares its address space and subnet collection, not
just additional subnets. Use `byo-existing` when you do not want that network deployment.
See [the user guide](USER-GUIDE.md#3-choose-your-network-model-and-planning-form)
for preparation requirements.

Both worksheets offer `network.outboundType=UserDefinedRouting` or `LoadBalancer`.
UDR requires a real, reachable firewall/NVA private IP in `network.nvaNextHop`, customer-provided
connectivity to it, firewall rules and SNAT. The tool does not create a firewall, NAT Gateway or
hub peering; an example next-hop IP is not a working egress path. `LoadBalancer` selects AKS
load-balancer-based outbound connectivity and does not require an NVA next hop; Stage 2 omits
its UDR tables. Neither choice removes the need to verify required outbound connectivity.
Both worksheets also require an existing customer-owned project storage account.

Example JSON files contain illustrative names and placeholder subscription/identity IDs;
replace them and review regions, subnet layout, storage and egress settings before use.
Recorded POC reports are historical, not fresh validation of the edited examples.
`examples/generated-config.json` is a historical serialization artifact, not a usable Stage 1
config; generate a new config from a filled form or a valid example input.

The `./out/` directory is created automatically, and Stage 1 only writes `config.json` once it
reaches a `GO` verdict — Stages 2–5 consume that file, so resolve any failing Stage 1 checks (or add
a `WAIVER` row) before continuing. Deny/audit policies are collected live from the subscription at
runtime; add a `POLICY` row only to declare or override one.

Run the commands from a `pwsh` (PowerShell 7+) prompt. On macOS/Linux they also run directly from
bash/zsh: each stage script is executable and starts with `#!/usr/bin/env pwsh`. If the executable
bit was lost (for example, after extracting a zip), run `chmod +x */*.ps1` here or use
`pwsh ./<stage>/<script>.ps1`.

```powershell
cd utilities/onboarding-tool/scripts   # all commands are relative to this directory

# Stage 1 — validate the planning form and emit the ground-truth config.
# (swap in discovery-resource-planning-form-byo-vnet.xlsx for the BYO-VNet path)
./stage1-planning/stage1_plan.ps1 -FormPath ./stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx -OutConfig ./config.json -JsonPath ./out/stage1.json

# Stage 2 — prepare the landing zone (writes resources, idempotent).
./stage2-landing-zone/stage2_prepare.ps1 -ConfigPath ./config.json -JsonPath ./out/stage2.json

# Stage 3 — static validation (read-only without -WithVm). Independently verify subnet egress.
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile supercomputer -JsonPath ./out/stage3-supercomputer.json
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile workspace -JsonPath ./out/stage3-workspace.json

# Stage 4 — deploy the platform in dependency order, gated on the Stage 3 GO reports.
./stage4-deployment/stage4_deploy.ps1 -ConfigPath ./config.json -ReadinessReport ./out/stage3-supercomputer.json,./out/stage3-workspace.json -JsonPath ./out/stage4.json

# Stage 5 — scenario enablement: create a Q&A agent and verify it answers a prompt.
./stage5-scenario-enablement/stage5_enable.ps1 -ConfigPath ./config.json -JsonPath ./out/stage5.json
```

Each command exits `0` only when every check passed (or was waived); non-zero otherwise, so the
stages chain in a pipeline. Each stage also writes a markdown report next to its `-JsonPath`
(`./out/stage1.md`, …); see the [user guide](USER-GUIDE.md#what-to-check-in-out-after-each-stage)
for what to check in `./out` after each stage.

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
`ImportExcel` module required. A `.json` config gets the same defaults as the form for any field it
omits (for example `network.model=byo`, which makes Stage 2 build the network); values present in
the JSON always win.

| Parameter | Required | Description |
|---|---|---|
| `-FormPath` | yes | Filled planning form (`.xlsx` or `.json`). |
| `-OutConfig` | no | Path to write the validated `config.json`. |
| `-JsonPath` | no | Write the machine-readable check report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

### Stage 2 — Landing zone (`stage2-landing-zone/stage2_prepare.ps1`)

Turns the signed `config.json` into a deployed landing zone (FR2.1–FR2.9): RP registration, RBAC
(Discovery roles and the administrator's Azure roles on the target resource groups, plus the
managed identity roles Stage 4 checks),
the one-time NSP Perimeter Joiner custom role plus Reader access for the Discovery control-plane
service principal, network provisioning via `network.bicep` (VNet,
subnets with FR1.2 delegations, shared NSG allow-list, UDR route tables, privatelink DNS zones +
links), BYO storage, and the firewall-request / quota-increase-request / policy-exemption-request
files next to `-JsonPath`. Builds the
network for the documented provisioning options managed/byo/byo-spoke; only byo-existing skips
network-template provisioning. Idempotent; stops on the first hard failure with its remediation. **Writes platform
resources — run against the intended subscription only.** Requires Owner, or Contributor plus
User Access Administrator / RBAC Administrator, at subscription scope.

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json`. |
| `-JsonPath` | no | Write the machine-readable build report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

### Stage 3 — Validation (`stage3-validation/stage3_validate.ps1`)

Validates network configuration before deployment (FR3.1–FR3.8). By default, runs read-only
Azure control-plane checks for subnet delegation, NSG rules, routes, private DNS zone links and
private-endpoint metadata. Where a NIC is available, checks use its effective NSG rules and
routes; otherwise they inspect subnet configuration. These checks do not test live connectivity.
The optional `-WithVm` probe harness has known limitations in this release; run Stage 3 without
it and arrange independent in-network connectivity testing. Probe improvements are planned
for the next version. The parameter remains available, but is not recommended for this release.
The profile check sets are defined in
[`dependency-spec.json`](stage3-validation/dependency-spec.json).
Requires a Stage 1 `GO` config and the landing zone prepared in Stage 2; `-WithVm` also requires
permission to create and delete probe resources in the target subnet.

> **Before deployment:** verify required AKS bootstrap connectivity from the SC system-node
> (`managedcluster`) and applicable nodepool subnets. A Stage 3 `GO` alone does not establish
> working DNS, firewall rules or SNAT. See [Known limitations and deployment checks](#known-limitations-and-deployment-checks)
> for probe restrictions and the checks your network team must complete.

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json`. |
| `-Profile` | no | `supercomputer` (default), `workspace`, or `bookshelf`. |
| `-WithVm` | no | Optional probe harness with known limitations in this release. Omit it; use independent subnet connectivity tests. Improvements are planned for the next version. |
| `-JsonPath` | no | Write the machine-readable check report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

### Stage 4 — Deployment (`stage4-deployment/stage4_deploy.ps1`)

Deploys the Discovery platform in dependency order (supercomputer → workspace → chatModel →
project storage container → project; Microsoft.Discovery api-version `2026-06-01`) and turns
every failure into an actionable remediation (`Resolve-DiscoveryError`). Detects true resource
state before each step so re-runs resume from the first incomplete resource. Deploys via
`discovery-platform.bicep` by default (params generated from the Stage 1 config); `-NoBicep` uses
the built-in per-resource ARM PUT sequence, `-Recovery` re-PUTs a stranded resource.
`controlPlaneRegion` must equal the region of the BYO VNet holding the managedcluster/nodepool
subnets. Supercomputer creation includes AKS provisioning and typically takes 15–30 minutes;
workspace creation can take up to about an hour, so plan for one to two hours end to end. Stage 4
waits up to 120 minutes per resource before reporting a timeout. **Writes
platform resources — run against the intended subscription only.**

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json` (with Stage 4 fields: resourceGroup, managedIdentity, storage). |
| `-Recovery` | no | Re-PUT a failed/stranded resource to recover a partial deployment. |
| `-NoBicep` | no | Use the built-in per-resource ARM PUT sequence instead of the default Bicep deploy. |
| `-BicepPath` / `-ParametersPath` | no | Deploy via a custom Bicep template/params instead of the shipped `discovery-platform.bicep`. |
| `-ReadinessReport` | no | One or more Stage 3 report paths (comma-separated). Pass both supercomputer and workspace reports; supplied reports must be GO. Omitting reports or supercomputer coverage produces a warning rather than blocking deployment. |
| `-Subscription` / `-ResourceGroup` / `-Workspace` | no | Override the config-derived targets. |
| `-JsonPath` | no | Write the machine-readable deployment report here. |
| `-PassThru` | no | Return raw result objects instead of printing a report and exiting. |

### Stage 5 — Scenario enablement (`stage5-scenario-enablement/stage5_enable.ps1`)

End-to-end certification of a Q&A agent (FR5.3–FR5.7). Creates a Discovery agent named
`scientistQnAAgent` with **no** Discovery tool bound, opens an investigation + conversation,
sends a scientific prompt, and verifies the agent answered with assistant text (passes only when
the response completes with a non-empty answer, not just an HTTP 200). Requires a green Stage 1
`config.json` and a successful Stage 4 deployment (workspace + project + chatModel live).
In-network connectivity probing is not part of Stage 5; it belongs to Stage 3.

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json`. |
| `-ResourceGroup` / `-Workspace` / `-Project` | no | Override the config-derived targets. |
| `-ChatModel` | no | Chat model deployment to use (defaults to the deployed one). |
| `-Prompt` | no | Override the default scientific Q&A prompt. |
| `-JsonPath` | no | Write the machine-readable certification report here. |

## Known limitations and deployment checks

Complete these checks before relying on the tool's reports for a customer deployment:

- **Stage 3 connectivity probes (current-release limitation):** omit `-WithVm` in this release
  and arrange approved connectivity tests from the required SC subnets before deployment.
  VM creation is blocked by the shared PowerShell wrapper rejecting the empty argument values
  used to request no public IP and no additional NSG. The probe also prefers the nodepool subnet,
  and incomplete output can use runner DNS or skip TCP/HTTPS checks. VM creation, lifecycle
  reliability and probe validation improvements are planned for the next version.
  If you attempted a probe, check for residual VM/NIC/disk resources.
- **UDR egress:** next-hop checks confirm that an address is provided, not that it identifies a
  reachable firewall/NVA. Have your network team verify the appliance IP, routing and hub
  connectivity, forwarding where applicable, firewall rules and SNAT. Confirm required AKS
  bootstrap endpoints are reachable from the actual SC node subnets before running Stage 4.
- **Readiness reports:** pass current Stage 3 supercomputer and workspace reports through
  `-ReadinessReport`. Stage 4 checks supplied reports for `GO`, but does not require reports
  or verify that they match the current configuration. Regenerate them after relevant
  configuration or infrastructure changes, and review warnings and skipped checks.
- **Bookshelf scope:** Stage 4 registers project storage (`Microsoft.Discovery/storageContainers`)
  but does not deploy Bookshelf or ingest its content. Arrange Bookshelf deployment separately
  if your solution requires it.
- **Scenario certification:** Stage 5 verifies a Q&A response and project-storage private-endpoint
  metadata when `storage.access=privateEndpoint`; the endpoint check is skipped for
  `serviceEndpoint`. Bookshelf retrieval and tool invocation require separate solution-specific
  validation.
- **Validation coverage:** this tool does not include an automated unit-test suite or CI
  validation workflow. Validate your deployment configuration in an approved test environment
  before production use.

## FR traceability

Each script header names its FR mapping and its spec file. Read a stage's requirements and
acceptance criteria in [`../Onboarding-Tooling-Requirements.md`](../Onboarding-Tooling-Requirements.md),
then the per-script spec in [`../script-specs/`](../script-specs/) for the contract.
