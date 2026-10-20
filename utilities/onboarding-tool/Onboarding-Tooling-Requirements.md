# Discovery Customer Onboarding — Tooling Requirements Spec

Requirement specifications for the script/tool that powers each of the five onboarding
stages. The target is a self-service flow: the customer drives every stage, each stage
has a machine-checked exit gate, and Microsoft is on standby for exceptions only.

Grounding for these requirements comes from two sources. Field evidence — concrete
checks, error signatures, and remediations — is drawn from a network-isolated
reference deployment's runbooks, MoPs, and ICM writeups, and the
onboarding proposal deck (`discovery-doc/onboarding/deck`). Authoritative constraints —
resource provider registration, role definitions, naming rules, and quota reservations —
are drawn from the Microsoft Discovery product docs:

- Resource provider registration: <https://learn.microsoft.com/azure/microsoft-discovery/concept-resource-provider-registration>
- Role assignments: <https://learn.microsoft.com/azure/microsoft-discovery/concept-role-assignments>
- Resource naming: <https://learn.microsoft.com/azure/microsoft-discovery/concept-resource-naming>
- Quota reservation: <https://learn.microsoft.com/azure/microsoft-discovery/concept-quota-reservation>

Where field evidence and the docs describe the same thing, the docs are the source of
truth for limits and identifiers; the field evidence supplies the failure signatures.

## Documentation boundaries

This document is the normative product specification: it defines required behavior, priorities
and acceptance criteria. Related documents have intentionally narrower purposes:

| Document | Owns | Does not own |
|---|---|---|
| [Customer user guide](scripts/USER-GUIDE.md) | Prerequisites, exact operator permissions, planning choices, commands, outputs and troubleshooting | Product requirement history or implementation contracts |
| [Scripts README](scripts/README.md) | Maintainer navigation and implementation map | Customer procedures or duplicated stage requirements |
| [Per-stage specifications](script-specs/) | Script inputs, outputs, folded checks and FR traceability | Customer runbook instructions |

When operational wording differs, the user guide governs how customers run the current release.
When expected behavior differs, this requirements specification governs and the implementation
must be reconciled.

## Stage map

| Stage | Tool | Owner | Exit gate |
|---|---|---|---|
| 1 Planning | Planning sheet with embedded validation | Customer + MSFT | Signed-off planning sheet (machine-readable config) |
| 2 Infra preparation | Landing-zone preparation automation | Customer | Landing zone deployed in customer subscription |
| 3 Infra validation | Validation toolbox + test-VM connectivity harness | Customer (self-service) | Green readiness report |
| 4 Platform deployment | Bicep deployer with error-to-remediation engine | Customer | Discovery platform running in tenant |
| 5 Scenario enablement | End-to-end scenario enablement script | Customer + MSFT | Platform certified ready |

## Execution permissions by stage

This matrix defines access for the **operator identity that runs each stage**. It does not describe
the target user personas that Stage 2 configures or the workload roles assigned to the platform
UAMI. Every eligible JIT/PIM role in the matrix must be activated before the stage starts.

In this specification, **Reader at target-subscription scope** means the Azure built-in Reader
role (`acdd72a7-3385-48ef-bd42-f606fba81ae7`) assigned at
`/subscriptions/<target-subscription-id>`, or inherited from a parent management group that
covers that subscription. A resource-group-only Reader assignment is insufficient because
Stages 1 and 3 read subscription/location-scoped providers, quotas, model catalogs and policies.
Microsoft Discovery Platform Reader (`3bb7c424-af4e-436b-bfcc-8779c8934c31`) is a different role
and does not satisfy this requirement. Owner or Contributor at subscription scope includes the
required reads, but Azure built-in Reader is the least-privilege built-in role for them.

| Stage | Minimum operator access | Scope | Conditional or optional access |
|---|---|---|---|
| 1 — Planning | Azure built-in Reader at target-subscription scope | Target subscription | Complete workspace-name validation also requires `Microsoft.Discovery/checkNameAvailability/action` at subscription scope; Microsoft Discovery Platform Administrator includes it. Without the action, the current implementation omits that check. Microsoft Entra directory read access is required when a principal is supplied by UPN/name rather than object ID. |
| 2 — Landing zone | Owner, **or** Contributor plus User Access Administrator | Target subscription | Contributor plus Role Based Access Control Administrator is sufficient only when the NSP Perimeter Joiner custom role already exists and `permanent-role-assignments` is selected. Role Based Access Control Administrator cannot create custom role definitions or PIM eligibility schedules. `customer-jit-managed` requires Owner or Contributor plus User Access Administrator and the required tenant license. |
| 3 — Static validation | Azure built-in Reader at target-subscription scope | Target subscription | When a usable NIC exists, Network Contributor is also required at the scope containing that NIC and the Network Watcher used for effective-NSG, effective-route and next-hop actions. The pre-deployment no-NIC path falls back to read-only subnet, NSG and route-table configuration. |
| 3 — `-WithVm` validation | Azure built-in Reader at target-subscription scope plus Contributor | Target subscription; probe VM resource group | If the VNet is in another RG, also grant Network Contributor on the VNet/subnet. Access must remain active through VM, NIC and disk cleanup. This mode is not recommended in the current release. |
| 4 — Platform deployment | Every role listed for the **Platform Administrator persona** under [Roles required by persona](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-role-assignments#roles-required-by-persona). A single Discovery role is not the complete permission set. | Every scope specified by Microsoft Learn for that persona, including scopes covering referenced network and UAMI resources | Permanent Foundry assignments in the new workspace managed RG require role-assignment authority there; JIT eligibility requires User Access Administrator or Owner. Assignment failure is a warning, not a platform-deployment failure. |
| 5 — Scenario enablement | Every role listed for the **Scientist persona** under [Roles required by persona](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-role-assignments#roles-required-by-persona). A single Discovery role is not the complete permission set. | Every scope specified by Microsoft Learn for that persona | Network reachability to the workspace data-plane endpoint when public access is disabled. |

The matrix is the normative stage-level permission contract. Customer-facing operation details,
least-privilege alternatives, PIM activation guidance and workload-identity roles are maintained in the
[user guide](scripts/USER-GUIDE.md#stage-by-stage-permissions). Functional requirements below
define the behavior that makes those permissions necessary.

## Shared design principles

These apply to every tool below.

- Config flows forward. Stage 1 emits one machine-readable config (the single source of
  truth); Stages 2–5 consume it. No stage re-asks for what Stage 1 captured.
- Every failure returns the exact remediation, not just a red mark.
- Read-only tools stay read-only against the customer subscription (Stage 3 validation).
  Only Stage 2 and Stage 4 write resources, and only what the config authorises.
- Machine plus human output. Every tool emits JSON for automation and a human-readable
  report, and exits non-zero on any failure so it can gate a pipeline.
- Cross-platform from one codebase: PowerShell 7 (`pwsh`) with Az CLI, which runs on Windows
  and macOS.
- Per-service scoping. Supercomputer, workspace, and bookshelf have different
  dependencies; checks and deploys are scoped by service profile, never one blanket pass.

## Requirement priorities

Every functional requirement is tagged `[P0]`, `[P1]`, or `[P2]` for development sequencing:

- P0 — MVP. Blocking; a stage cannot ship or gate without it. Build these first.
- P1 — required for the self-service GA. The flow works without it but is not yet
  hands-off or fully diagnostic.
- P2 — enhancement. Improves UX or coverage; defer past first GA.

The P0 set across all five stages is the minimum viable onboarding pipeline. Each stage's
acceptance criteria are met when its P0 and P1 requirements pass.

## Script decomposition

Each stage has one consolidated PowerShell 7 + Azure CLI script and one matching contract under
`script-specs/`. Stage 1 emits the config defined by `script-specs/config.schema.json`; Stages 2–5
consume it. Shared behavior lives in `scripts/lib/OnboardingCommon.psm1`.

Use the [scripts README](scripts/README.md) for the implementation map, the
[per-stage spec index](script-specs/README.md) for contracts and FR traceability, and the
[customer user guide](scripts/USER-GUIDE.md) for execution.

---

## Stage 1 — Planning sheet with embedded validation

### Overview

The customer performs deployment planning in a planning sheet, extending the network-planning
form template (`network-planning-form-template.xlsx`). The sheet collects everything a
deployment needs: subscription id, control-plane and workload regions, deployment size, and —
for bring-your-own network — the VNet and per-service subnet CIDRs, NSGs, and route/DNS intent.
The output is a machine-readable JSON config that becomes the single source of truth for every
later stage.

### Purpose

Capture the deployment parameters and validate them at fill-in time, so subnet, region,
quota, naming, and policy conflicts surface while the customer is still typing — not three
weeks later in a failed deployment.

### Inputs

- Customer network / security / policy documentation.
- Existing VNet address space and subnet inventory (if bring-your-own network).
- Target subscription id and the assigned policy set.

### Output / exit gate

- Signed-off planning sheet.
- A machine-readable config export (JSON/YAML) that becomes the single source of truth for
  Stages 2–5.

### Functional requirements

FR1.0 [P0] Subscription prerequisites. Confirm the subscription is enabled for Discovery by the
Microsoft Discovery team (an allowlist gate — resources cannot be created otherwise) and
that `Microsoft.Discovery` and its dependent resource providers are registered (Stage 2
performs the registration; Stage 1 records the requirement and the deploying identity's
role). Registration needs Contributor or Owner, or a custom role with the RP
`/register/action`.

FR1.1 [P0] Capture fields: control-plane region, workload region, VNet CIDR, per-service subnet
CIDRs, BYO storage model, deploying identity, the policy set, and mandatory
`rbac.humanAccessMode` (`permanent-role-assignments` or `customer-jit-managed`). The JIT mode also
requires `rbac.jitEligibilityDurationDays` as a whole number from 7 through 3650.

FR1.2 [P0] Embedded subnet-sizing validation. Validate each Discovery subnet against the
required prefix and confirm all fit inside the provided VNet without overlap:

| Subnet role | Required prefix | Delegation |
|---|---|---|
| agent container app | /26 | `Microsoft.App/environments` |
| workspace container app | /26 | `Microsoft.App/environments` |
| search container app | /27 | `Microsoft.App/environments` |
| AKS managed cluster (system nodes) | /26 | none |
| AKS node pool (×2) | /26 each | none |
| private endpoints | /27 | none |
| spare / management (AKS API-server VNet integration) | /27 | `Microsoft.ContainerService/managedClusters` when `outboundType=UserDefinedRouting`; otherwise unused |

The reference layout (agent /26, workspace /26, search /27, PE /27, AKS /26, nodepool /26)
fits inside a single /23. Provide the /24 agent-subnet fallback when a region rejects the
packed layout.

FR1.3 [P0] Address-space conflict detection. Flag overlap with existing subnets and insufficient
free space in the VNet.

FR1.4 [P0] Region availability check. Validate the workload region actually offers the features
Discovery needs, and distinguish capacity from quota — capacity exhaustion presents even
when quota is healthy. Specifically flag AKS API Server VNet Integration capacity
(`AKSCapacityHeavyUsage` was hit in eastus2) and AI Search regional capacity. Recommend the
workload/control-plane split where a region is capacity-limited.

FR1.5 [P0] Quota and SKU validation. Check vCPU by family, GPU SKUs, private-endpoint count, and
Foundry/OpenAI TPM. Resolve the effective Stage 4 system/node SKUs and maximum node count (including
advanced JSON overrides), pin SKU and usage reads to the configured subscription, and calculate
Total Regional plus VM-family vCPU requirements from live SKU metadata. Flag SKUs that are absent
or restricted in the target region. Validate the documented Discovery quota minimums so shortfalls
surface in planning, not deployment:

Cosmos DB throughput (autoscale RU/s), sized `2,400 + 400 × projects`:

| Resource | Minimum RU/s | Autoscale max |
|---|---|---|
| workspace | 2,400 | 4,000 |
| project (each) | 400 | 4,000 |

Model TPM (per workspace, single Bookshelf; multiply Bookshelf models per instance):

| Model | Service | Minimum TPM | Recommended TPM |
|---|---|---|---|
| GPT-5.4 | Discovery Engine (cognition, auto-provisioned) | 250,000 | 1,000,000 |
| GPT-5.4 | validation deployment `gpt-5-4` (manual) | 200,000 | 250,000 |
| GPT-5.4 | Agents / Copilot | 200,000 | 1,000,000 |
| GPT-5.2 | Bookshelf (per instance) | 200,000 | 2,000,000 |
| GPT-5 Mini | Bookshelf (per instance) | 2,000,000 | 10,000,000 |
| Text Embedding 3 Small | Bookshelf (per instance) | 2,000,000 | 2,000,000 |

For the current baseline deployment, ensure at least 450,000 TPM of GPT-5.4 Global Standard is
free: 250,000 for the workspace's built-in deployment plus 200,000 for the `gpt-5-4` validation
deployment. On a resumed deployment, count only allocations that do not already exist in
`Succeeded` state. Validate both `Microsoft.CognitiveServices/locations/usages/read` quota data
and `Microsoft.CognitiveServices/locations/models/read` regional catalog metadata, including the
OpenAI provider, GlobalStandard SKU, matching usage name, resolver-selected version, lifecycle,
quota status and 1K-TPM capacity-unit metadata. Reader at subscription scope grants both read
operations; Cognitive Services Usages Reader alone does not grant the model-catalog read.
Bookshelf indexing pulls an
on-demand supercomputer nodepool sized by tier — Small `Standard_D48s_v6`, Medium
`Standard_D128s_v6`, Large `Standard_D192s_v6` — plus an always-on Azure AI Search
Standard S1 and an ACA dedicated profile; account for these when a Bookshelf is in scope.

FR1.6 [P1] Name-collision and naming-rule validation. Enforce the per-type rules (lowercase
alphanumeric plus hyphens, must start with a letter, no consecutive separators) and the
length/pattern limits, and reserve the managed-resource-group names the platform
auto-creates so they do not collide:

| Resource | Length | Notes |
|---|---|---|
| workspace | 3–24 | also the endpoint subdomain; end with letter or digit |
| project | 3–12 | hyphen separators |
| supercomputer | 3–24 | end with letter or digit |
| node pool | 3–12 | |
| tool | 3–24 | letters may be upper or lower case |
| agent | 3–63 | start and end alphanumeric |
| storage container | 3–24 | start and end with a letter |
| storage asset | 3–24 | |
| investigation | 1–20 | start and end with a letter |

Auto-created MRGs: `mrg-dwsp-<workspace>-<6char>`, `mrg-dscmp-<supercomputer>-<6char>`,
`mrg-dbksf-<bookshelf>-<6char>`. Use `Microsoft.Discovery/checkNameAvailability` for
workspace uniqueness.

FR1.7 [P1] Policy collection and pre-flight. Collect the policy assignments effective at the
target subscription (including inherited management-group assignments) via
`az policy assignment list --disable-scope-strict-match`, resolve each assignment's policy type
(BuiltIn/Custom) and effect (from the assignment `effect` override or the definition default),
and inspect them: cross-check declared and live assignment names against the known deny policies
that block Discovery (see Stage 2 table) and flag each with its remediation (exemption vs
configuration change); separately surface any custom restrictive policy (effect deny, denyAction,
modify, deployIfNotExists, append) so customer-specific blockers are caught before Stage 2. Skip
gracefully when `az` is not logged in and warn when the assignments cannot be read.

FR1.8 [P0] Emit the config export only when all embedded validations pass or are explicitly
waived with a recorded justification.

### Acceptance criteria

- A sheet with a bad subnet size, an overlapping CIDR, a capacity-blocked region, or a
  known deny policy cannot export a "clean" config without an explicit waiver note.
- The exported config round-trips into Stage 2 and Stage 3 with no re-entry.

---

## Stage 2 — Landing-zone preparation automation

### Overview

This stage prepares the customer landing zone from the signed config: RBAC assignment,
resource-provider registration, quota allocation, and the policy exception requests the
deployment needs. It writes into the customer subscription, so it needs Owner at subscription
scope, or the combination of Contributor plus User Access Administrator. An
access-administration role alone cannot provision the landing zone, and Contributor alone cannot
create its role assignments and custom role. Contributor plus Role Based Access Control
Administrator is sufficient only after the NSP custom role exists and only for permanent human
role assignments.

### Purpose

Turn the signed planning config into a deployed landing zone: identity, network, storage,
private DNS, quota requests, and policy exemptions — idempotently.

### Inputs

- Stage 1 config export.
- Deploying identity and target subscription/resource groups.

### Output / exit gate

- Landing zone deployed in the customer subscription.
- A generated firewall/NVA request artifact for the customer network team.

### Functional requirements

FR2.1 [P0] Resource providers and RBAC. Register `Microsoft.Discovery` and its dependent
providers (`az provider register --namespace Microsoft.Discovery`, then verify each is
`Registered`); the dependencies include `Microsoft.Network`, `Microsoft.Compute`,
`Microsoft.Storage`, `Microsoft.ManagedIdentity`, `Microsoft.Authorization`,
`Microsoft.CognitiveServices`, `Microsoft.ContainerService`, `Microsoft.ContainerRegistry`,
`Microsoft.DocumentDB`, `Microsoft.KeyVault`, `Microsoft.MachineLearningServices`,
`Microsoft.NetApp`, `Microsoft.Search`, `Microsoft.Web`, `Microsoft.App`,
`Microsoft.Insights`, `Microsoft.OperationalInsights`, `Microsoft.Sql`, and
`Microsoft.Bing` (full list in the RP-registration doc). Then assign the Discovery
built-in roles, scoped to the target resource groups (assigning them requires Owner, User
Access Administrator, or Role Based Access Control Administrator at the scope):

| Role | Definition ID | Use |
|---|---|---|
| Platform Administrator | `7a2b6e6c-472e-4b39-8878-a26eb63d75c6` | deploying identity — full control-plane + data-plane |
| Platform Contributor | `01288891-85ee-45a7-b367-9db3b752fc65` | scientists — operate resources, no infra create/delete |
| Platform Reader | `3bb7c424-af4e-436b-bfcc-8779c8934c31` | reviewers — read-only |
| Bookshelf Index Data Reader | `8ec773c5-7ce6-4b78-91d1-182f8faa536d` | agents querying knowledge bases |

Microsoft Discovery Platform Administrator can create standard role assignments only within the
scope where that role is assigned. It cannot create subscription custom-role definitions or PIM
eligibility schedules, and a platform-RG assignment does not cover the workspace managed RG. For
project-scoped users, pair Project Contributor/Reader with the resource-specific roles
(Tools Reader, Chat Model Reader, Storage Container Reader/Contributor); the storage
container roles do not grant blob access, so add Storage Blob Data Reader/Contributor on
the backing storage scope.

Human user assignment modes:

| Mode | Tool behavior | Customer action |
|---|---|---|
| `permanent-role-assignments` | Create standard role assignments. | None for assignment activation. |
| `customer-jit-managed` | Create or reuse time-bound PIM eligibility with `Microsoft.Authorization/roleEligibilityScheduleRequests` and `requestType=AdminAssign`. | Activate required roles in PIM after Stage 2. |

Eligible-but-inactive is not a Stage 2 failure. Service-principal and managed-identity assignments
remain persistent.

FR2.1a [P0] NSP Perimeter Joiner custom role. Network hardening is on by default, so before the
first workspace/supercomputer/bookshelf deploy, create the one-time-per-subscription custom
role that lets the Discovery control-plane service principal (app ID
`92c174ac-8e41-4815-a1b7-d81b19ab03ce`) join managed PaaS resources to the workspace NSP.
It needs exactly `Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action` and
`Microsoft.Network/locations/networkSecurityPerimeterOperationStatuses/read`, assigned at
subscription scope. Creating the definition requires
`Microsoft.Authorization/roleDefinitions/write`, which Owner and User Access Administrator
provide but Role Based Access Control Administrator does not. Without the role, resource creation
fails with NSP association errors.

FR2.2 [P0] BYO network provisioning from config, deployed declaratively via `network.bicep`
(one RG-scoped deployment covering FR2.2-FR2.5): VNet, subnets with the delegations from FR1.2,
a shared NSG, route tables, and privatelink DNS zones. The step runs only when `network.model`
uses a documented provisioning option (`managed`/`byo`/`byo-spoke`); `byo-existing` skips this
network deployment and validates existing networking in Stage 3. All build models use the
same template and can modify an existing VNet's address space and subnet collection.
The managed planning form offers `managed`; the BYO form offers `byo` (customer-defined
provisioning), `byo-spoke` (spoke provisioning with customer-arranged hub connectivity), and
`byo-existing` (customer-prepared existing network).
See the [planning-form guide](scripts/USER-GUIDE.md#3-complete-the-planning-form-choices).
Egress topology is switched separately by `network.outboundType`
(UserDefinedRouting builds NVA route tables; LoadBalancer omits user route tables).
Neither form provisions a firewall/NVA, NAT Gateway or hub peering. UDR requires customer-provided
appliance connectivity, firewall rules and SNAT.

FR2.3 [P0] NSG rule set. Apply the required rules per subnet NSG:

- `Allow-AzureLB-In` — source `AzureLoadBalancer`, any port.
- `Allow-PodCIDR-In` — source `10.244.0.0/16`, dest VNet CIDR + pod CIDR, any port.
- `Allow-DNS-Out` — dest corp DNS `/32`, port 53.
- `Allow-<PaaS>-Out` (443) for service tags: `Storage.<region>`, `AzureKeyVault.<region>`,
  `AzureCosmosDB.<region>`, `AzureCognitiveSearch`, `AzureActiveDirectory`, `AzureMonitor`,
  `AzureContainerRegistry.<region>` + `MicrosoftContainerRegistry`, `AzureResourceManager`.
- `Allow-Internet-Out` (443) to `Internet` — required, not optional; bootstrap hits CDNs
  with IPs in no service tag.
- `Allow-PodCIDR-Out` — dest `10.244.0.0/16`, any port.
- No inbound DNS rule needed when the resolver is outside these subnets (NSGs are stateful).

FR2.4 [P0] Route tables. Keep `0.0.0.0/0` and `10.0.0.0/8` pointed at the NVA. Set the managed
cluster subnet route to `<managedcluster-CIDR> -> VnetLocal`. Routes must be delete +
recreate, never in-place update (in-place fails `NextHopIpAddressNotAllowed`). Do not add a
VnetLocal carve-out to any other subnet.

FR2.5 [P0] Private DNS zones. Create and link the `privatelink.*` zones the platform needs:
`cognitiveservices.azure.com`, `openai.azure.com`, `services.ai.azure.com`,
`search.windows.net`, `vaultcore.azure.net`, `blob.core.windows.net`,
`documents.azure.com`, `azurecr.io`.

FR2.6 [P1] BYO storage account and access model from config.

FR2.7 [P0] NVA/firewall request artifact. Emit the network-rule and FQDN allowlist the customer
firewall team must apply, using the actual spoke CIDR from config (a wrong source CIDR
caused a 675× deny bootstrap loop):

- Network rules: DNS 53, Azure PaaS 443, NTP 123/UDP.
- AKS bootstrap FQDNs (443, plus 80 for the first two): `packages.microsoft.com`,
  `mcr.microsoft.com`, `*.data.mcr.microsoft.com`, `acs-mirror.azureedge.net`,
  `management.azure.com`, `login.microsoftonline.com`.
- Discovery/Foundry PaaS FQDNs: `*.cognitiveservices.azure.com`, `*.openai.azure.com`,
  `*.services.ai.azure.com`, `*.search.windows.net`, `*.vault.azure.net`,
  `*.blob.core.windows.net` (and queue/table/file/dfs), `*.documents.azure.com`,
  `*.azurecr.io`, `*.azurecontainerapps.io`, `*.monitor.azure.com`, `*.windows.net`.
- East-west allow between Discovery subnets. Emit the specific-port fallback when any/any is
  not permitted (10250, 443, 53 TCP+UDP, 80; optional 4443 and NodePort range), referencing
  `firewall-request-discovery-eastwest.md`.

FR2.8 [P1] Quota and exemption requests. Generate the quota-increase requests from FR1.5 gaps,
and the policy-exemption requests for deny policies that have no configuration fix:

| Policy | What it blocks | Handling |
|---|---|---|
| Cognitive Services public network access disallowed | the Foundry account auto-created in the workspace MRG | exemption still required — an RP fix is planned but not yet shipped; apply a time-bound waiver on the workspace MRG allowing public network access on the Foundry account |
| Log Analytics public access disallowed | the Log Analytics workspace in its MRG | exemption required — allow public IP ingestion/query access on the Log Analytics MRG |
| Storage public access disallowed | Bookshelf MRG storage account | time-bound waiver on the Bookshelf MRG, non-prod first, NSP enforced |
| NSP association | managed-resource NSP association during provision | ordering/retry, plus the FR2.1a Perimeter Joiner role — not a policy exemption |

Container Apps HTTPS-only (`allowInsecure`) no longer needs handling: it has been fixed in
the RP (the platform now provisions internal Container Apps with `allowInsecure:false`), so
no exemption or configuration change is required. The tool should not emit a request for it.

FR2.9 [P1] Idempotent re-run. Re-running with the same config converges without duplicate or
conflicting resources.

### Acceptance criteria

- From a clean subscription and a Stage 1 config, the tool produces a landing zone that
  passes Stage 3 without manual network edits.
- The firewall artifact uses the real spoke CIDR and lists every FQDN above.

---

## Stage 3 — Infra validation toolbox (load-bearing)

### Overview

Validation walks the prerequisite checklist and confirms each item is satisfied, read-only, so
the customer can re-run it without a Microsoft round trip. As an optional step it creates a
disposable VM in the target subnet to confirm real connectivity through the firewall/NVA, then
deletes it.

### Purpose

Convert "we think the network is ready" into a machine-checked, self-service yes/no that the
customer can re-run without a Microsoft round trip. The networking confirmation runs from a
disposable test VM created in the target resource group.

**Deployment guidance for this release:** run Stage 3 without `-WithVm`. The optional probe
harness has known VM-creation and connectivity-validation limitations; improvements are
planned for the next version. Stage 3 runs static checks by default. Before deployment, confirm
the configured firewall/NVA is reachable and verify required outbound connectivity from the SC
node subnets; a static GO alone does not establish either. See the current-release guidance in the
[Stage 3 user guide](scripts/USER-GUIDE.md#stage-3--validate-readiness-read-only).

### Architecture requirements

FR3.1 [P0] One engine, two front ends: a headless CLI for pipelines and a VS Code extension with
a guided checklist, one-click re-run, and deep links to failing resources. The CLI is P0;
the VS Code extension is P2 and can follow after the CLI ships.

FR3.2 [P1] Cross-platform (Windows + macOS) from one codebase.

FR3.3 [P1] Per-service profiles: supercomputer, workspace, bookshelf — each checks only its own
dependencies.

FR3.4 [P0] Strictly read-only against the customer subscription, except for the ephemeral test VM
it creates and deletes in FR3.7.

FR3.5 [P0] Emit JSON plus a human report; exit non-zero on any failure.

FR3.6 [P1] Every failed check carries its remediation string (see the failure catalog).

### Control-plane checks (read-only, per profile)

FR3.6a [P0] Subnet delegations match FR1.2.

FR3.6b [P0] NSG effective rules include the FR2.3 set; confirm `Allow-Internet-Out` 443 and the
east-west path exist. Use `az network nic list-effective-nsg`. A subnet with no NSG passes, since
the Azure default rules allow both paths.

FR3.6c [P0] Effective routes correct: managed cluster subnet resolves to `VnetLocal`, others to
the NVA. Use `az network nic show-effective-route-table` and `az network watcher
show-next-hop`.

FR3.6d [P0] Private DNS zones from FR2.5 exist and are linked; private endpoints are `Approved`
with non-empty DNS (Bookshelf expects 3 PEs approved, Foundry endpoint carries 2 zones).

FR3.6e [P0] Re-check the FR1.5 quota right before deploy, because subscription quota can drop
between Stage 1 and Stage 4. The supercomputer profile checks vCPU quota and the workspace profile
checks gpt-5.4 GlobalStandard TPM (450K). A shortfall blocks Stage 4 unless waived; a target
resource that already exists in `Succeeded` state is skipped because it already holds its quota.

### Test-VM connectivity harness (the core requirement)

FR3.7 [P0] Provision a disposable VM in the target subnet, run the probe suite, then delete it:

```bash
az vm create -g $rg -n $vm \
  --image Canonical:0001-com-ubuntu-server-jammy:22_04-lts-gen2:latest \
  --size <region-allowed-SKU> --subnet "$subnetId" \
  --public-ip-address "" --nsg "" \
  --admin-username azureuser --generate-ssh-keys
az vm run-command invoke -g $rg -n $vm --command-id RunShellScript --scripts @conntest.sh
```

FR3.7a [P0] DNS resolution. For each of `mcr.microsoft.com`, `packages.aks.azure.com`,
`packages.microsoft.com`, `management.azure.com`, `login.microsoftonline.com`,
`<region>.data.mcr.microsoft.com`: `getent hosts` must return an IP. Missing IP = DNS FAIL.

FR3.7b [P0] TCP 443 reachability via `/dev/tcp/$h/443` — expect `443 OPEN`.

FR3.7c [P0] HTTPS status via `curl -o /dev/null -w "%{http_code}"`: `mcr.microsoft.com/v2/` → 200,
`packages.aks.azure.com/` → 400, `management.azure.com/` → 400/401,
`login.microsoftonline.com/` → 200.

FR3.7d [P1] Real artifact pulls: the `packages-microsoft-prod.deb`, the kubelet node bundle
(`kubernetes-node-linux-amd64.tar.gz` ranged GET), and the Ubuntu mirror `Release` (HTTP
200). These prove the NVA is not TLS-inspecting or dropping the FQDN.

FR3.7e [P0] Private-endpoint resolution: each `privatelink.*` FQDN resolves to a private IP, not a
public one.

FR3.7f [P1] East-west: from a node-subnet probe confirm the managed cluster subnet reaches the
node subnets on TCP 10250.

FR3.7g [P0] Always delete the test VM (and its NIC/disk) on exit, pass or fail.

### Failure catalog (check → remediation)

| Symptom | Remediation |
|---|---|
| `DNS FAIL` | Fix VNet DNS / private DNS zone links |
| DNS ok, `443 BLOCKED` | NSG denies egress or UDR black-holes the route |
| TCP open, HTTPS/deb/binary fails | NVA allowlist incomplete or TLS-inspecting the FQDN |
| Public FQDN → private IP (or reverse) | Fix private DNS zone links / VNet DNS |
| API server → kubelet 10250 `TLS handshake timeout` | Allow east-west 10250 (symmetric routing or explicit rule) |
| Managed cluster routed via NVA, AKS NotReady | Set managed cluster subnet to VnetLocal; delete+recreate route |
| `nslookup` times out, firewall saw the response | Return-path asymmetry — restore symmetry / HA session sync / pin node |

### Dependency spec dependency

FR3.8 [P1] The toolbox reads a per-service dependency spec that is dev-owned and updated in the
same PR as any feature that adds or changes an infra dependency. A validator checking last
quarter's dependencies is worse than none.

### Acceptance criteria

- A landing zone with a missing east-west rule or an unlinked private DNS zone produces a
  red readiness report naming the exact fix.
- A fully prepared landing zone produces a green report and leaves no test VM behind.

---

## Stage 4 — Bicep deployer with error-to-remediation engine

### Overview

Deployment runs the Bicep templates in dependency order. No extra tooling is required beyond
making sure a failure surfaces the true cause with an actionable remediation instead of a raw
ARM error. The Bicep should ship as part of the product.

### Purpose

Deploy the platform in dependency order, and when a step fails, surface the true cause with
a specific remediation instead of a raw ARM error.

### Inputs

- Green readiness report (gate).
- Stage 1 config; Bicep templates and parameters.

### Output / exit gate

- Discovery platform running in the customer tenant.

### Functional requirements

FR4.1 [P0] Deploy in dependency order and gate each on `Succeeded`:
supercomputer → workspace (`properties.supercomputerIds`) → chat model → project →
bookshelf. If the supercomputer is `Failed`, do not touch the workspace; fix it first. The
chat-model step must create the validation deployment named `gpt-5-4` (model `gpt-5.4`)
explicitly — the cognition deployment is auto-provisioned at workspace creation, but without
the manual `gpt-5-4` deployment the Discovery Engine cannot validate task results and won't
start.

FR4.2 [P0] Use api-version `2026-06-01` for all `Microsoft.Discovery` ARM resources
(workspaces, supercomputers, projects, tools) and for the workspace data plane. The
earlier tools-only `2026-02-01-preview` is superseded — do not use it.

FR4.3 [P0] True-state detection. ARM resource-list can show `Succeeded` while a Foundry account is
still `Creating`; confirm with `az cognitiveservices account show` and enforce a timeout that
converts a stuck `Accepted`/`Creating` into a terminal, actionable failure. Pass only when both
states are `Succeeded`; a `Failed` ARM state is never overridden by the Foundry state.

FR4.4 [P1] Error-to-remediation engine. Match the ARM error signature and emit the remediation:

| Error signature | Root cause | Remediation |
|---|---|---|
| `AKSCapacityHeavyUsage` / `InternalServerError` on AKS create | region capacity for API Server VNet Integration | retry, or deploy workload in a region with capacity and global-peer to the firewall |
| `AZFWApplicationRule` deny on `packages.microsoft.com` (repeated) | firewall rule source scoped to wrong CIDR | add the real spoke CIDR to firewall source addresses; allow the bootstrap FQDNs |
| `409 FlagMustBeSetForRestore` | Foundry account soft-deleted then recreated | set `Restore=true`, or purge and wait before re-PUT |
| `RequestDisallowedByPolicy` on Foundry / Cognitive Services account | workspace-MRG Foundry account with `publicNetworkAccess=Enabled` | apply the workspace-MRG exemption (RP fix planned, not yet shipped) |
| `RequestDisallowedByPolicy` on Log Analytics workspace | Log Analytics MRG public access disallowed | apply the Log Analytics MRG public-access exemption |
| Storage public-access policy deny | Bookshelf MRG storage `publicNetworkAccess=Enabled` | apply the Bookshelf MRG exemption, or move to PE architecture |
| `No CustomDnsConfigs found on PE` | private endpoint not approved / no DNS configs | approve PE (Pending) or recreate (Rejected/Disconnected); success = Approved, dnsCount 3 |
| NSP association `InternalServerError`, terminal `Failed` | NSP association raced provisioning | retry with backoff after convergence |

FR4.5 [P1] Built-in recovery. Provide the targeted re-PUT path for a workspace-only failure
(`workspace_reput.py --subscription --resource-group --workspace`) and the ordered
post-recovery creation of chat model then project.

FR4.6 [P1] Every deploy step logs the resource, provisioning state, and — on failure — the matched
remediation from FR4.4; exit non-zero.

### Acceptance criteria

- Each catalogued failure is reported with its remediation, never as a bare ARM error.
- A false `Succeeded` is caught by FR4.3 rather than passed downstream.

---

## Stage 5 — Scenario enablement script

### Overview

An optional certification that runs a hero workflow end to end to prove the platform works
before it is handed off to the customer application team. A hero workflow (use case) needs to
be chosen as the standard.

### Purpose

Prove the platform actually works: connectivity, then a real agent run that genuinely
invokes a tool on the supercomputer. A completed run alone does not certify anything.

### Inputs

- Running Discovery platform; workspace, project, and chat-model deployment names.

### Output / exit gate

- Platform certified ready for customer applications.

### Functional requirements

FR5.1 [P0] Connectivity check first: private DNS resolution and endpoint reachability from inside
the VNet (reuse the Stage 3 harness against the platform private endpoints).

FR5.2 [P0] Create a tool via ARM PUT
`https://management.azure.com${TOOL_ARM_ID}?api-version=2026-06-01`; verify
`provisioningState=Succeeded` and `definitionContent` present. The tool JSON must carry
`version`, `definitionContent` (name/description/version/category/infra[]), and
`code_environments[].infra_node` matching an `infra[].name`.

FR5.3 [P0] Create the agent and bind the tool via
`POST ${BASE}/projects/${PROJECT}:upsertAgent`. `tools[]` is top-level with the tool ARM id;
`humanInTheLoop:"Disabled"`, `confirmation:"Disabled"`; `foundryDetails.definition.kind =
"prompt"` with `model` = chat-model deployment name. Agent instructions must call
`GetNodePoolContext` first, or the model may answer from memory and never touch the
supercomputer.

FR5.4 [P0] Create investigation, then conversation:

- `PUT ${BASE}/projects/${PROJECT}/investigations/${INV}`
- `POST ${BASE}/conversations` with `investigationName =
  /projects/${PROJECT}/investigations/${INV}` and `projectName`.

FR5.5 [P0] Send the hero prompt and poll:

- `POST ${BASE}/conversations/${CONV}/openai/v1/responses`
- `GET ${BASE}/conversations/${CONV}/openai/v1/responses/${RID}`

FR5.6 [P0] Hard pass/fail on real tool invocation. `status: completed` is not sufficient; the
response `output` must contain a `function_call` / `function_call_output` item, and the run
must be visible in Foundry tracing. Absence of a tool-call item is a FAIL.

FR5.7 [P1] Per-service verification summary: supercomputer/workspace/Foundry/project/chat-model
all `Succeeded`; project storage (BYO storage account behind the project's storage container) private endpoint approved with DNS; tool created; agent created;
tool bound; conversation completed; tool actually invoked.

### Acceptance criteria

- A run that completes without a `function_call` item is reported as not certified.
- On success the script emits the per-service summary and a certification verdict.

**Current implementation boundary:** FR5.6/FR5.7 tool-invocation requirements above describe
the target scope, not the shipped Stage 5 behavior. The script creates a Q&A agent with no tool,
requires a completed non-empty assistant answer, and checks project-storage endpoint metadata
for privateEndpoint access (skipped for serviceEndpoint). It does not deploy Bookshelf or certify
Bookshelf retrieval/tool invocation. See the
[Stage 5 specification](script-specs/stage5-scenario-enablement/stage5_enable.md).

---
