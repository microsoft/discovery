# Microsoft Discovery onboarding — user guide

This guide walks you, step by step, through using the onboarding tool to **prepare**, **validate**,
and **deploy** the Azure resources for a Microsoft Discovery environment. It is written for the
operator who will actually run the scripts. Follow it top to bottom the first time; after that you
can jump straight to [The five stages](#the-five-stages). Everything you need is in this document —
no other files are required reading.

---

## 1. What the tool does

The tool is a **five-stage pipeline**. Each stage is one PowerShell script. Run the stages in order.
Live runs report **GO** with exit `0`, or **NO-GO** with remediation and a non-zero exit.
Offline dry runs of Stages 2-5 report `PLAN`, not a readiness or certification verdict.

| Stage | Script | What it does | Writes resources? |
|---|---|---|---|
| 1 Planning | `stage1-planning/stage1_plan.ps1` | Reads your planning form, validates it, emits `config.json` | No |
| 2 Landing zone | `stage2-landing-zone/stage2_prepare.ps1` | Registers RPs, assigns RBAC, provisions the network | Yes |
| 3 Validation | `stage3-validation/stage3_validate.ps1` | Read-only readiness checks before deployment | No |
| 4 Deployment | `stage4-deployment/stage4_deploy.ps1` | Deploys the Discovery platform in dependency order | Yes |
| 5 Scenario enablement | `stage5-scenario-enablement/stage5_enable.ps1` | Creates a Q&A agent and verifies it answers | Yes (one agent) |

**Config flows forward.** Stage 1 produces `config.json`; Stages 2–5 read it and never re-ask for
anything Stage 1 already captured. Fix Stage 1 before moving on — a bad plan can't be deployed.

---

## 2. Before you start (prerequisites)

### Preview a stage offline

Stages 2-5 accept `-DryRun` with a Stage 1 `config.json`. This mode requires only
PowerShell 7: no Azure CLI, login or Azure permissions. It reads the config and lists
intended actions without Azure calls, resource changes, VM creation or inference.
The tool writes local JSON and Markdown plan reports only when you supply `-JsonPath`.

From the `scripts` directory:

```powershell
.\stage2-landing-zone\stage2_prepare.ps1 -ConfigPath .\config.json -DryRun -JsonPath .\out\stage2-plan.json
.\stage3-validation\stage3_validate.ps1 -ConfigPath .\config.json -Profile workspace -DryRun -JsonPath .\out\stage3-plan.json
.\stage4-deployment\stage4_deploy.ps1 -ConfigPath .\config.json -DryRun -JsonPath .\out\stage4-plan.json
.\stage5-scenario-enablement\stage5_enable.ps1 -ConfigPath .\config.json -DryRun -JsonPath .\out\stage5-plan.json
```

The verdict is `PLAN`, not `GO` or certification. Results are `Skip` because nothing
was executed. Exit `0` means the plan was generated, not that the environment is ready;
invalid or missing config fails. A Stage 3 plan cannot satisfy Stage 4's readiness gate.
This is an intent summary, not Azure what-if: existing state, permissions, quota, policy,
capacity and connectivity are not evaluated. Remove `-DryRun` to execute the stage.

The plan includes stage options such as `-Profile`, `-WithVm`, Stage 4 `-Recovery` and Stage 5 target overrides.
`-WithVm -DryRun` only describes the VM lifecycle.
Use `-PassThru` to return plan result objects without printing or writing reports.
`-PassThru` takes precedence over `-JsonPath` in dry-run mode.
Dry run checks required config fields and the RBAC mode, not every deployment prerequisite.
Stage 1 already performs planning and does not accept `-DryRun`.

### Live execution prerequisites

Install and sign in once:

1. **PowerShell 7+** — every script declares `#Requires -Version 7.0`.
   ```powershell
   pwsh --version   # expect 7.x
   ```
   Run the stage commands in this guide from a `pwsh` prompt. On macOS or Linux you can also run
   them directly from bash/zsh: the scripts are executable and start with `#!/usr/bin/env pwsh`, so
   `pwsh` must be on your `PATH`. If a copy lost the executable bit (for example, files extracted
   from a zip by a tool that drops permissions), restore it with
   `chmod +x */*.ps1` from the `scripts` directory, or run a stage as `pwsh ./<stage>/<script>.ps1`.
2. **Azure CLI**, logged in to the subscription you will deploy into:
   ```powershell
   az login
   az account set --subscription <your-subscription-id>
   az account show --query '{name:name, id:id}' -o table
   ```
3. **Confirm the operator has the roles for each stage.** Do not use one subscription-wide
   administrator identity for the entire onboarding flow. Activate elevated access only for the
   stage that needs it, then return to the narrower role shown below.

   ### Stage-by-stage permissions

   These are the roles for the **signed-in person running the script**. They are different from the
   roles Stage 2 assigns to users and the roles assigned to the platform managed identity. If a role
   is PIM-eligible, activate it before starting the applicable stage; eligibility alone is not active
   access.

   In this guide, **Reader at target-subscription scope** means the Azure built-in **Reader** role
   (`acdd72a7-3385-48ef-bd42-f606fba81ae7`) assigned at
   `/subscriptions/<target-subscription-id>`, or inherited from a parent management group that
   covers that subscription. Reader on only the platform or network resource group is insufficient:
   the scripts also read subscription/location-scoped providers, quotas, model catalogs and policies.
   Microsoft Discovery Platform Reader is a different role and does not replace this subscription
   Reader requirement. Owner or Contributor at subscription scope includes the required reads, but
   Reader is the least-privilege built-in choice for these read operations.

   | Stage and execution path | Required operator access | Required scope | Checks or actions performed |
   |---|---|---|---|
   | 1 — Core planning and Azure readiness | Azure built-in **Reader at target-subscription scope** | Target subscription | <ul><li>Required form fields and RBAC mode</li><li>Subnet sizing, delegation, fit, and overlap</li><li>Egress and workspace network settings</li><li>Discovery provider, UAMI, VNet, and storage existence</li><li>Required VM SKUs and regional/VM-family vCPU quota</li><li>GPT-5.4 catalog and TPM quota</li><li>Cosmos sizing and naming syntax</li><li>Policy assignments visible at subscription scope</li></ul>Cognitive Services Usages Reader alone is insufficient. |
   | 1 — Additional checks when additional access is granted | Add: a custom role with `Microsoft.Discovery/checkNameAvailability/action`, or **Microsoft Discovery Platform Administrator**; parent-scope **Reader** or **Resource Policy Reader** when inherited policy definitions apply; customer-approved Microsoft Entra directory read access only when resolving a principal name | Target subscription; applicable parent management group; target tenant | <ul><li>Workspace-name availability</li><li>Inherited policy definitions and effective deny behavior</li><li>User or service-principal name resolution to an Entra object ID</li></ul>Supplying an object ID avoids directory lookup. Without an additional permission, only its corresponding check is unavailable. |
   | 2 — Landing-zone preparation | **Owner**, **or** **Contributor** plus **User Access Administrator** | Target subscription | <ul><li>Register required resource providers</li><li>Create or update the NSP Perimeter Joiner custom role</li><li>Assign customer and workload-identity RBAC or PIM eligibility</li><li>Create the managed VNet, subnets, and delegations</li><li>Prepare quota-exemption requests</li></ul>**Contributor** plus **Role Based Access Control Administrator** is sufficient only when the custom role already exists and permanent assignments are selected. Customer-managed JIT requires Owner or Contributor plus User Access Administrator and the required tenant license. |
   | 3 — Baseline configuration and Azure readiness (default) | Azure built-in **Reader at target-subscription scope** | Target subscription | <ul><li>Subnet sizing and delegation</li><li>Configured NSG rules and route tables</li><li>Private DNS zones and VNet links</li><li>Private endpoints</li><li>Discovery resource state</li><li>Required VM SKUs and compute quota</li><li>GPT-5.4 model catalog and quota</li></ul>Always runs. Uses configuration evidence; it does not create resources or prove packet-level connectivity. An unreadable quota check fails the stage. |
   | 3 — Live effective-network checks (automatically added when a usable NIC exists) | Baseline **Reader** plus **Network Contributor**, or a custom role with the three required actions | **Reader:** target subscription. **Network Contributor/custom role:** only the resource group or resource scopes containing the existing NIC and Network Watcher; subscription scope is not required. | <ul><li>Azure-calculated effective NSG rules</li><li>Azure-calculated effective routes</li><li>Network Watcher next hop</li></ul>Uses the existing NIC and creates no VM. Required actions: <code>networkInterfaces/effectiveNetworkSecurityGroups/action</code>, <code>networkInterfaces/effectiveRouteTable/action</code>, and <code>networkWatchers/nextHop/action</code>. |
   | 3 — Active in-VNet connectivity probe (optional `-WithVm`) | Baseline **Reader** plus **Contributor** on the probe RG | **Reader:** target subscription. **Contributor:** probe resource group only. If the VNet is in another RG, **Network Contributor:** VNet or subnet scope only. Contributor and Network Contributor do not need subscription scope. | <ul><li>DNS resolution from inside the VNet</li><li>HTTPS reachability</li><li>Route and next-hop behavior</li><li>Private-endpoint reachability</li><li>Temporary VM, NIC, and disk creation and cleanup</li></ul>Keep access active through cleanup. This mode is not recommended in this release. |
   | 4 — Platform deployment | Assign every role listed for the **Platform Administrator persona** under [Roles required by persona](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-role-assignments#roles-required-by-persona). Do not treat one Discovery role as the complete permission set. | Use each scope specified by Microsoft Learn for the Platform Administrator persona, including scopes covering referenced network and UAMI resources. | <ul><li>Deploy the supercomputer, workspace, model, storage container, and project</li><li>Assign Foundry roles in the workspace managed RG when authorized</li></ul>Permanent Foundry assignments require role-assignment authority; JIT eligibility requires User Access Administrator or Owner. A missing Foundry assignment is a warning rather than a platform-deployment failure. |
   | 5 — Scenario enablement | Assign every role listed for the **Scientist persona** under [Roles required by persona](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-role-assignments#roles-required-by-persona). Do not treat one Discovery role as the complete permission set. | Use each scope specified by Microsoft Learn for the Scientist persona. | <ul><li>Create the Q&amp;A agent</li><li>Create a temporary investigation and conversation</li><li>Send a validation prompt and verify a completed non-empty answer</li><li>Validate project storage private-endpoint DNS</li></ul>Run from a network location that can reach the workspace data plane when public access is disabled. |

4. **A subscription enabled (allow-listed) for Microsoft Discovery.** If
   `Microsoft.Discovery` is not visible in the subscription, contact your Microsoft account
   representative to request access. Stage 1 treats an invisible provider as a blocking failure.
5. **A resource group** for the platform (Stage 4 deploys into it). Create it if needed:
   ```powershell
   az group create -n <your-rg> -l <region>
   ```
6. **A user-assigned managed identity (UAMI)** — **required for Stage 4**. The tool does **not**
   create this for you; you must pre-create it and record its resource id in the config
   (`managedIdentity.id`). Create one with:
   ```powershell
   az identity create -g <your-rg> -n <your-uami-name> --query id -o tsv
   ```
   Copy the printed resource id; you will put it in the planning form / config.

   Stage 2 assigns the UAMI its roles. The supercomputer's AKS identities and the workspace all
   run as this UAMI:

   | Role | Scope |
   |---|---|
   | Microsoft Discovery Platform Contributor | your platform resource group |
   | Storage Blob Data Contributor | your platform resource group |
   | AcrPull | your platform resource group |
   | Network Contributor | the VNet (the network resource group if the VNet isn't found) |

   If whoever runs Stage 2 can't create role assignments, have an Owner or User Access
   Administrator assign them:

   ```powershell
   $p  = az identity show -g <your-rg> -n <your-uami-name> --query principalId -o tsv
   $rg = az group show -n <your-rg> --query id -o tsv
   $net = az network vnet show -g <network-rg> -n <vnet-name> --query id -o tsv
   foreach ($r in 'Microsoft Discovery Platform Contributor','Storage Blob Data Contributor','AcrPull') {
     az role assignment create --assignee-object-id $p --assignee-principal-type ServicePrincipal --role $r --scope $rg
   }
   az role assignment create --assignee-object-id $p --assignee-principal-type ServicePrincipal --role 'Network Contributor' --scope $net
   ```
   Allow 5–10 minutes for role propagation. Stage 4 checks every role and stops before deploying
   if any is missing, printing the exact `az` commands to fix it.
7. **Compute and model quota** in the deployment region. By default, the supercomputer system pool
   runs 3 × `Standard_D4s_v6` (12 vCPUs), and the node pool can scale to 3 ×
   `Standard_D4ds_v6` (12 more vCPUs). Advanced JSON configs can override `systemSku`,
   `nodePoolVmSize`, and `nodePoolMaxNodeCount`. Stage 1 reads the selected subscription's live SKU
   metadata to calculate the effective Total Regional and VM-family vCPU requirements; Stage 3
   repeats the same check before deployment. Check current usage with
   `az vm list-usage -l <region> --subscription <subscription-id> -o table`. Each workspace also uses 450K GPT-5.4 GlobalStandard
   TPM (250K for the built-in deployment plus 200K for the validation chat model). GlobalStandard
   quota is scoped by subscription, region, model, and deployment type. Stage 1 verifies the
   required model/SKU and free TPM; Stage 3 re-checks them before Stage 4. On a resumed deployment,
   the check counts only allocations that still need to be created. Subscription **Reader** covers
   both quota usage and regional model-catalog reads. **Cognitive Services Usages Reader** covers
   quota usage only and is not sufficient for the complete Stage 1 check. A missing portal row is
   not equivalent to zero quota. AI Search capacity for Bookshelf isn't checked.
8. **A storage account** for project data, required for every deployment. The tool doesn't
   create it. Create a StorageV2 account in the target subscription and put its name in
   `storage.account` (or its resource ID in `storage.accountId`):
   ```powershell
   az storage account create -g <your-rg> -n <globally-unique-name> -l <region> --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false
   ```
   Stage 1 checks that it exists. Stage 2 then sets its network default action to Deny, adds the
   Discovery Studio CORS rule and the containers, and creates the blob private endpoint.

> `ImportExcel` is **not** required. Stage 1 reads `.xlsx` forms natively.

---

## 3. Complete the planning form choices

There are **two** planning forms. Pick the form, then explicitly select `network.model`:

| Form | Available VNet options | Use this form when |
|---|---|---|
| [Managed VNet](stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx) | `managed` only | You want the tool to provision a dedicated Discovery network layout. |
| [BYO VNet](stage1-planning/discovery-resource-planning-form-byo-vnet.xlsx) | `byo`, `byo-spoke`, `byo-existing` | You want customer-defined provisioning, an enterprise-hub spoke, or validation of a customer-prepared existing network. |

The same option sets apply to copies of these forms. A previously filled cell can retain an
old value after a dropdown changes, so check the selected value before running Stage 1.
**The value of `network.model`, not the worksheet filename, controls provisioning.**

### What each VNet option means

| Option | When to use it | What the tool does | What the customer prepares |
|---|---|---|---|
| `managed` (managed form) | The tool should provision the Discovery network layout. | Stage 2 deploys the VNet, configured subnets and delegations, shared NSG, route tables for UDR, and private DNS zones/links. | Approved address space, target resource group/name settings, and a working outbound architecture. |
| `byo` (BYO form) | You supply the network layout and want the tool to provision it. | Uses the same Stage 2 network template as `managed`; it is not a read-only existing-VNet mode. | Customer-approved network settings and outbound connectivity. |
| `byo-spoke` (BYO form) | You want a Discovery spoke connected to an enterprise hub. | Uses the same Stage 2 network template; it does not create hub peering or a firewall. | Nonoverlapping spoke addressing, hub connectivity, and firewall/NVA routing, rules and SNAT when using UDR. |
| `byo-existing` (BYO form) | Your network team has already prepared the VNet and required Discovery subnets. | Stage 1 checks the existing VNet/subnets; Stage 2 skips network-template provisioning; Stage 3 validates networking. | Existing subnets, delegations, NSGs, routes, DNS zones/links and working outbound connectivity. |

**Existing-network caution:** `managed`, `byo` and `byo-spoke` all deploy a template that declares
the VNet address space and subnet collection. They can change an existing VNet and are not
add-only subnet operations. Use `byo-existing` to avoid that deployment. Stage 2 still performs
its other tasks, including RBAC and project-storage networking; `byo-existing` does not make
the entire stage read-only.

### Choose outbound connectivity separately

Both forms offer two `network.outboundType` values, independently of `network.model`:

- **`UserDefinedRouting`:** route outbound traffic through the real firewall/NVA private IP in
  `network.nvaNextHop`. The customer must provide connectivity to that appliance, forwarding
  where applicable, firewall allow rules and SNAT. Do not leave an example IP unless it is
  genuinely the configured appliance. Stage 2 generates a firewall request but does not apply
  the appliance rules or create hub peering.
- **`LoadBalancer`:** select AKS load-balancer-based outbound connectivity. An NVA next-hop IP
  is not required, and Stage 2 does not create UDR tables. This does not create a NAT Gateway
  or guarantee that customer network controls permit all required endpoints.

**Managed means tool-provisioned network layout, not managed firewall or guaranteed Internet
access.** Verify required AKS bootstrap connectivity from the SC node subnets before deploying.
Static Stage 3 checks alone do not prove that the outbound path works.
Project storage is separate: both forms require an existing customer-owned StorageV2 account.

### Choose how human role assignments are managed

Both forms require `rbac.humanAccessMode`:

| Option | What the tool creates for users | What the customer does |
|---|---|---|
| `permanent-role-assignments` | Standard Azure role assignments in Stages 2 and 4. | No PIM activation is required for these assignments. |
| `customer-jit-managed` | Time-bound PIM eligibility in Stages 2 and 4. For new eligibility, `rbac.jitEligibilityDurationDays` must be from 7 through 3650. | After Stage 2, activate the required roles before Stage 3/4 or interactive use. Activate Foundry roles created by Stage 4 before using the workspace. |

This choice applies only to users. The tool continues to create persistent role assignments for
service principals and managed identities.

Open the form, go to the **`Config`** sheet, and fill in every **yellow Value cell**. The form is
organized into sections (identity & subscription, regions, network, storage, sizing, names, etc.).
Notes next to each field explain what to enter. A few that trip people up:

| Field | What to enter |
|---|---|
| `subscriptionId` | The subscription you ran `az account set` against. |
| `deployingIdentity.objectId` | The identity that will deploy. If `principals` is empty, Stage 2 grants it the Discovery roles plus the Azure roles a Discovery administrator needs (Managed Identity Contributor and Operator, Storage Account Contributor, Storage Blob Data Contributor, Network Contributor, AcrPush) on the target resource groups plus Reader on the subscription, and Stage 4 grants it Foundry Owner on the workspace managed resource group. Enter the Entra **objectId (GUID)**, or — if you don't know it — an **email/UPN** of a user in the target tenant (or an app registration's appId/display name). Stage 1 resolves a non-GUID value to the objectId via `az` (run `az login` first). Find your own objectId with `az ad signed-in-user show --query id -o tsv`. |
| `resourceGroup` | The platform resource group from prerequisite 5. |
| `managedIdentity.id` | The UAMI resource id from prerequisite 6 (used by Stage 4). |
| `rbac.humanAccessMode` | Select `permanent-role-assignments` or `customer-jit-managed` as described above. |
| `rbac.jitEligibilityDurationDays` | Required only for `customer-jit-managed`. Enter the requested duration for new eligibility as a whole number from 7 through 3650. This is not an activation window. |
| `network.model` | Choose one of the options described above. Only `byo-existing` skips Stage 2 network-template provisioning. |
| `network.networkResourceGroup` | The resource group holding the existing VNet for `byo-existing`, or the target group for tool-provisioned networking. Stage 2 creates/uses the target network group for provisioning models. |
| `network.dnsResourceGroup` | Resource group containing the private DNS zones linked to the Discovery VNet. Leave it blank when DNS zones live in `network.networkResourceGroup`; specify it for centralized DNS in another resource group. Stage 2 creates/reuses the required zones and exact VNet links there and includes this RG in its RBAC targets. |
| `network.vnetName` | For `byo-existing`, enter the existing VNet name (Stage 1 checks it exists and is in `workloadRegion`). For `managed`, `byo` or `byo-spoke`, enter the VNet name to deploy; blank defaults to `vnet-<names.workspace>`. |
| `network.existingSubnets` | BYO form: list existing subnet CIDRs outside the planned Discovery subnets so address planning can check for overlaps. This field does not make a provisioning model preserve unlisted subnets. |
| `network.outboundType` | Select `UserDefinedRouting` for customer firewall/NVA egress, or `LoadBalancer` for AKS load-balancer-based egress. |
| `network.nvaNextHop` | For UDR, enter the actual firewall/NVA private IP. It is not a NAT Gateway public IP. Not required for `LoadBalancer`. |
| `controlPlaneRegion` / `workloadRegion` | Use a supported production region: **East US**, **Sweden Central**, or **UK South**. `controlPlaneRegion` places the Discovery control-plane resources and can differ from `workloadRegion`. The VNet/subnets and all resources in the managed resource groups (MRGs) must be in `workloadRegion`. |
| `names.*` | The resource names (workspace, project, supercomputer, node pool, etc.). Keep them unique in the subscription. |
| `storage.account` | Required for every project, independently of Bookshelf. The name of the storage account you pre-created (prerequisite 8); keep `storage.model=byo`. Stage 1 fails if the account doesn't exist. Stage 2 adds the Blob CORS rules and private endpoint. The account denies public network traffic, so users who open project outputs in Discovery Studio need network access to it: from the VNet (VPN or ExpressRoute), or through a client IP rule you add. |
| `workspace.publicNetworkAccess` | `Enabled` (default) or `Disabled`. With `Disabled`, the workspace data plane (agents, investigations, conversations) answers only from inside the VNet, so Stage 5 must run from a runner with private network access. |
| `workspace.networkIsolation` | `true` (default) isolates the Workbench and requires VPN or ExpressRoute to the workspace VNet. `false` enables authenticated public Workbench access. This setting is independent of `workspace.publicNetworkAccess`. |

Notes:
- **Policies are collected live** from the subscription at runtime — you do not list deny/audit
  policies in the form. Add a `POLICY` row only to declare or override one.
- For **`byo-existing`**, `workloadRegion` must equal the existing VNet region.
  `controlPlaneRegion` does not need to match it.
- For **`byo-existing`**, Stage 2 skips the VNet/network-template deployment. Before Stage 3, make sure that:
  - Each SUBNET row's CIDR matches an existing subnet. Stage 1 maps rows to subnet names by CIDR
    and fails `byo-subnets` on a mismatch.
  - The workspace, agent and search subnets are delegated to `Microsoft.App/environments`, and the
    management subnet to `Microsoft.ContainerService/managedClusters`.
  - The `privatelink.*` zones listed under `privateDnsZones` in
    `stage3-validation/dependency-spec.json` exist in `network.dnsResourceGroup` (or the network
    RG) and are linked to the exact VNet resolved from `network.networkResourceGroup`. With
    `byo-existing`, Stage 2 skips the network-template DNS
    deployment. For `storage.access=privateEndpoint`, it reuses the blob zone in that DNS/network
    RG, verifies its VNet link, and associates the storage endpoint's DNS zone group with it.
    Stage 3 prints create/link commands for missing zones.
  - Any NSG you attach allows outbound 443 to Internet and traffic within the VNet. A subnet
    without an NSG passes, because the Azure default rules allow both.

---

## 4. One-time setup for the commands

All commands below are **relative to the `scripts/` directory**, so start there:

```powershell
cd utilities/onboarding-tool/scripts
```

The `./out/` directory is created automatically and holds the JSON reports and request artifacts.
It is git-ignored — safe for run output. You generally keep `config.json` in this folder too.

---

## 5. The five stages

Run these in order. **Only advance when a stage prints `GO` and exits `0`.** Each `-JsonPath`
writes a machine-readable report you can keep or feed into a pipeline.

### Stage 1 — Plan (validate the form, emit `config.json`)

**Scope:** read-only. Touches nothing in Azure except read-only lookups (region availability,
quota/SKU, policy pre-flight). Its only output is `config.json` plus the JSON report.

**Operator access:** **Reader** on the target subscription plus the conditional action, policy and
directory access in [Stage-by-stage permissions](#stage-by-stage-permissions).

Run this command from the `utilities/onboarding-tool/scripts` directory. If your prompt is at the
repository root, run `cd utilities/onboarding-tool/scripts` first.

```powershell
# Managed VNet form (swap in the byo-vnet form for the BYO path):
./stage1-planning/stage1_plan.ps1 `
  -FormPath ./stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx `
  -OutConfig ./config.json `
  -JsonPath ./out/stage1.json
```

- Validates every planning rule (subnet sizing, address-space conflicts, region availability,
  quota/SKU, naming, policy pre-flight).
- Writes `config.json` **only** when all required checks pass (or carry a recorded `WAIVER` row).
- Az-dependent checks degrade to Warn/Skip if you are not logged in, so the parser still runs
  offline — but log in for a real run.

**If it fails:** read the remediation on each red row, fix the yellow cell in the form (or add a
`WAIVER`/`POLICY` row where appropriate), and re-run. Do not continue until you get `config.json`.

A `policy-preflight` failure means a deny policy will block Discovery provisioning. To proceed:

1. Clear the Stage 1 gate with a row in the Config sheet: column A `WAIVER`, B `policy-preflight`,
   C the justification (required), D the approver.
2. Before Stage 4, create the Azure policy exemption. Stage 2 writes the exact
   `az policy exemption create` command per assignment to `./out/policy-exemption-requests-<workspace>.md`.
   The WAIVER row only clears the tool's gate; without the exemption, Stage 4 still fails.

### Stage 2 — Prepare the landing zone (writes resources)

**Scope:** **writes to Azure.** Registers resource providers, assigns RBAC roles, and provisions
networking in the target subscription / resource group. Run against the intended subscription only.

**Operator access:** **Owner**, or **Contributor** plus **User Access Administrator**, at
target-subscription scope. **Role Based Access Control Administrator** is a narrower alternative
only when the NSP custom role already exists and `permanent-role-assignments` is selected.

```powershell
./stage2-landing-zone/stage2_prepare.ps1 -ConfigPath ./config.json -JsonPath ./out/stage2.json
```

- Registers resource providers, assigns RBAC, creates the one-time NSP Perimeter Joiner role,
  assigns both that role and **Reader** to the Discovery control-plane service principal, and
  (for managed / byo / byo-spoke) provisions the VNet, subnets with the
  required delegations, shared NSG allow-list, route tables, and private DNS zones.
- RBAC covers the Discovery roles and the administrator's Azure roles on the target resource
  groups, plus the UAMI roles from prerequisite 6 after the network and storage exist.
- With `customer-jit-managed`, creates or reuses PIM eligibility for user roles and writes
  `human-pim-eligibility-<workspace>.md/.json`. Eligible roles are not active until each customer
  user activates them in PIM. This reminder is a warning, not a Stage 2 failure.
- Also emits firewall-request, quota-increase-request, and policy-exemption-request files next to
  `-JsonPath` (`./out/`). For UDR, the network team must confirm the required rules are applied
  and the appliance provides working egress; writing the firewall request is not that confirmation.
  Resolve applicable quota/governance requests with the owning teams before deployment.
- **Idempotent** — safe to re-run; it stops on the first hard failure with its remediation.

> This stage writes to Azure. Make sure you are pointed at the intended subscription
> (`az account show`).

### Stage 3 — Validate readiness (read-only)

**Scope:** read-only Azure control-plane checks unless `-WithVm` is supplied. That option invokes
the temporary probe VM lifecycle and attempts cleanup on exit. A plain run creates no Azure
resources, but writes local reports when requested.

**Operator access:** **Reader** on the target subscription for the recommended no-VM path. See
[Stage-by-stage permissions](#stage-by-stage-permissions) for the conditional
effective-network actions and additional `-WithVm` roles.

```powershell
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile supercomputer -JsonPath ./out/stage3-supercomputer.json
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile workspace     -JsonPath ./out/stage3-workspace.json
```

- Static checks before deployment: subnet delegation, NSG rules, routes, private DNS zone links
  and private-endpoint metadata. Where a NIC is unavailable, NSG/route checks inspect subnet
  configuration rather than effective NIC rules. These are not live DNS/endpoint tests.
- `-Profile` selects the check set: `supercomputer` (default), `workspace`, or `bookshelf`. Run
  **both `supercomputer` and `workspace`**: Stage 4 deploys both, and each profile checks only its
  own subnets (supercomputer: managedcluster, nodepool, spare; workspace: container-app and
  private-endpoint subnets).
- **Omit `-WithVm` in this release.** The optional probe harness has a known VM-creation issue
  and does not provide complete connectivity validation across the required SC subnets.
  VM creation, lifecycle reliability and probe validation improvements are planned for the
  next version. The commands above run static checks only; arrange independent in-network
  connectivity tests before deployment. The parameter remains available, but is not
  recommended for this release.
- **A static `GO` is not sufficient evidence of working outbound connectivity.** Before Stage 4,
  have the network team verify routing, appliance connectivity, firewall rules and SNAT, and
  test required AKS bootstrap DNS/TCP/TLS and image downloads from the actual SC node subnets.
  Use an approved existing node/VM or an explicitly approved temporary probe; do not test only
  from your laptop or Cloud Shell. For troubleshooting, see
  [AKS outbound connection failure guidance](https://learn.microsoft.com/en-us/troubleshoot/azure/azure-kubernetes/create-upgrade-delete/error-code-outboundconnfailvmextensionerror).
- **Customer deployment checks:** confirm that the configured next-hop IP identifies your
  reachable firewall/NVA and retain successful connectivity evidence from the required SC
  subnets. Generate fresh Stage 3 reports after relevant configuration or network changes and
  pass both profiles to Stage 4. The scripts do not require this connectivity evidence or
  verify that readiness reports match the current configuration.

### Stage 4 — Deploy the platform (writes resources)

**Scope:** **writes to Azure.** Creates the Discovery platform resources in the target resource
group. Re-runnable: it detects real resource state and resumes from the first incomplete resource.

**Operator access:** assign every role listed for the **Platform Administrator persona** under
[Roles required by persona](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-role-assignments#roles-required-by-persona),
using the scopes documented there and covering referenced network and UAMI dependencies. Do not
treat Microsoft Discovery Platform Administrator as the complete permission set by itself.
Stage 2's subscription-level **Owner** or **Contributor** access is not required for platform
deployment. Separate role-assignment authority is needed only if this runner must also assign
Foundry roles in the new workspace managed resource group.

```powershell
./stage4-deployment/stage4_deploy.ps1 -ConfigPath ./config.json -ReadinessReport ./out/stage3-supercomputer.json,./out/stage3-workspace.json -JsonPath ./out/stage4.json
```

- `-ReadinessReport` takes one or more Stage 3 reports (comma-separated); Stage 4 refuses to write
  unless every one is `GO`, and warns if none covers the `supercomputer` profile.
  Without it, Stage 4 still runs but flags the missing gate as a warning.
- Deploys in dependency order: **supercomputer → workspace → chatModel → project storage
  container → project**, using Discovery
  api-version `2026-06-01` via `discovery-platform.bicep`.
- Does not deploy Bookshelf or ingest Bookshelf content, even when `bookshelf.inScope=true`.
  Project storage is required independently of Bookshelf. Its Discovery container name is
  `names.storageContainer`; when blank, Stage 4 appends `-storage` to a workspace-name prefix and
  truncates that prefix as needed to stay within the 24-character limit. Reruns reuse an existing
  valid legacy `<workspace>-bookshelf` container when no explicit name is supplied.
- Detects real resource state before each step, so a re-run **resumes** from the first incomplete
  resource. Use `-Recovery` to re-PUT a stranded resource.
- After the project, assigns Foundry roles on the workspace managed resource group: Foundry Owner
  to `principals` with Platform Administrator (else `deployingIdentity`), and Foundry User to
  Platform Contributor principals. A failure here is a warning.
- **Plan for Stage 4 to take one to two hours.** Supercomputer creation includes AKS provisioning
  and typically takes 15–30 minutes. Workspace creation, which provisions its managed Foundry
  account and model deployment, can take up to about an hour. Stage 4 waits up to 120 minutes for
  each resource during resource-state polling; exceeding that limit is a timeout. Keep the session open
  until it completes; if it's interrupted, re-run the same command and Stage 4 resumes from the
  first incomplete resource.
- Requires the Stage 4 config fields: `resourceGroup`, `managedIdentity.id` (your pre-created UAMI),
  and `storage`.

**`InternalServerError` caveat:** if the supercomputer fails a few minutes after submit with
`InternalServerError (target=internalMetadata)` and its managed resource group stays empty, check:

1. **Subnet topology:** Stage 4's `supercomputer subnet topology` check must pass. The `aksSubnet`
   (managedcluster) subnet must have **no delegation**, because the supercomputer system nodes run
   there. A `Microsoft.ContainerService/managedClusters` delegation belongs only on the separate
   `managementSubnet`, which is used only with `UserDefinedRouting`.
2. **UAMI roles:** Stage 4's `managed identity role assignments` check must pass (prerequisite 6).

Then delete the Failed supercomputer
(`az resource delete --ids <supercomputer id> --api-version 2026-06-01`) and re-run Stage 4. If
both checks pass and it still fails, open a support case with the correlation id from the report,
or try a confirmed region such as **`eastus`**.

### Stage 5 — Enable and certify a scenario (creates one agent)

**Scope:** **writes to Azure** — one Discovery agent (`scientistQnAAgent`) plus a throw-away
investigation/conversation used for the test. No tool is created.

**Operator access:** assign every role listed for the **Scientist persona** under
[Roles required by persona](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-role-assignments#roles-required-by-persona),
using the scopes documented there. Do not treat Microsoft Discovery Platform Contributor as the
complete permission set by itself.

```powershell
./stage5-scenario-enablement/stage5_enable.ps1 -ConfigPath ./config.json -JsonPath ./out/stage5.json
```

- Creates a Discovery agent named **`scientistQnAAgent`** (no tool bound), opens an investigation +
  conversation, sends a scientific Q&A prompt, and verifies the agent returns a **completed,
  non-empty answer**.
- In-network connectivity (private DNS and 443 reachability from inside the VNet) is not checked
  here; it belongs to Stage 3.
- Stage 5 first probes the workspace data plane from your machine. If
  `workspace.publicNetworkAccess=Disabled` and you are outside the VNet, the probe fails and the
  remaining steps are skipped. Run from inside the VNet, or set the field to `Enabled` and re-run
  Stage 4.
- Override the prompt with `-Prompt "<your question>"` if you want to test a different question.
- Verifies project storage for every deployment: an Approved blob private endpoint with DNS
  when `storage.access=privateEndpoint`; the endpoint check is skipped for `serviceEndpoint`.
  This is not a Bookshelf retrieval or tool-invocation test.

---

## 6. Reading the results

- **Verdict line:** each stage ends with `GO` (exit `0`) or `NO-GO` (non-zero). Only a `GO` lets you
  advance.
- **Per-check rows:** every check shows Pass / Fail / Warn / Skip. **Every failure carries an exact
  remediation string** — read it; it tells you what to change.
- **Reports:** every stage writes its `-JsonPath` report plus a markdown report with the same name
  (`./out/stage1.md`, …). Open the `.md` first; the `.json` is for records or pipeline gating.
- **Artifacts:** Stage 2 writes firewall-request, quota-increase-request, and policy-exemption-request
  files (markdown plus JSON) under `./out/` for the teams that own those approvals.

### What to check in `./out` after each stage

Report names follow `-JsonPath`: `-JsonPath ./out/stage1.json` produces `./out/stage1.json` and
`./out/stage1.md`. Other files are written to the same folder. The table uses the names from the
commands above; `<workspace>` is the workspace name from `config.json`.

| Stage | Files | What to check |
|---|---|---|
| 1 | `stage1.md`, `stage1.json`; `config.json` is written to the `-OutConfig` path (`./config.json`), not `./out` | Verdict is GO and `config.json` exists. Read the remediation on any Fail; a Warn must not hide a real gap (quota, region, policy). Review `config.json` names, subnets, and identity before Stage 2. |
| 2 | `stage2.md`, `stage2.json`, `firewall-request-<workspace>.md/.json`, `quota-increase-requests-<workspace>.md/.json`, `policy-exemption-requests-<workspace>.md/.json`; with JIT, `human-pim-eligibility-<workspace>.md/.json` | Verdict is GO. Resolve applicable requests with the owning teams. With JIT, activate required user roles. For UDR, confirm firewall rules and working egress, not merely request approval. |
| 3 | `stage3-supercomputer.md/.json`, `stage3-workspace.md/.json` | Both reports are GO. Review Warn/Skip rows and independently verify required subnet egress. Stage 4 reads supplied reports through `-ReadinessReport`, but does not require them or bind them to the current config. |
| 4 | `stage4.md`, `stage4.json` | Verdict is GO and deployed resources (supercomputer, node pool, workspace, chat model, project storage container and project) show Succeeded with resource IDs. Bookshelf is not deployed. On failure, inspect the ARM error and remediation. |
| 5 | `stage5.md`, `stage5.json`, `stage5-response-<timestamp>.json`, `stage5-state-<timestamp>.json` | Verdict is GO. The response file holds the agent's answer; confirm it is `completed` and the text answers the prompt. The state file records the agent, investigation, and conversation used by the test. |

---

## 7. Common issues and fixes

| Symptom | Fix |
|---|---|
| Stage 1 won't write `config.json` | One or more required checks failed. Fix the flagged yellow cell (or add a `WAIVER`/`POLICY` row), then re-run. |
| "Not logged in" / Az checks skipped | `az login` and `az account set --subscription <id>`, then re-run. |
| Stage 2 RBAC failure | For a clean subscription or JIT mode, get **Owner**, or **Contributor** plus **User Access Administrator**, at subscription scope. **Role Based Access Control Administrator** works only for permanent assignments after the NSP custom role exists. |
| Stage 2 reports customer PIM activation required | Give the customer IAM team the generated `human-pim-eligibility-<workspace>.md` artifact. Stage 2 has created or verified eligibility and intentionally does not fail because the role is not active yet. Each user must activate the required role before the next operation that depends on it. |
| `RequestDisallowedByPolicy` while assigning a user | Do not disable the policy as routine remediation. Select `customer-jit-managed` and use the customer PIM/JIT process, or obtain a policy-approved exception. |
| Stage 4 fails on `managedIdentity` | `managedIdentity.id` is missing or wrong. Pre-create the UAMI (prerequisite 6) and set its resource id in the form, re-run Stage 1, then Stage 4. |
| Stage 4 fails `managed identity role assignments` | The UAMI is missing a required role. Run the `az role assignment create` commands printed in the report, wait 5–10 minutes, then re-run Stage 4. |
| Stage 4 fails `supercomputer subnet topology` | The `aksSubnet` is delegated, or `UserDefinedRouting` has no delegated `managementSubnet`. Run the `az network vnet subnet update` command printed in the report, re-run Stage 3, then Stage 4. |
| Stage 4 supercomputer `InternalServerError` | Check the subnet-topology and UAMI-role checks first (see the Stage 4 caveat). Delete the Failed supercomputer, then re-run. If both pass, open a support case with the correlation id. |
| AKS `VMExtensionError_OutboundConnFail`, exit 50, or failure reaching `mcr.microsoft.com` | Verify the real NVA next hop, routing/peering, DNS, firewall allows and SNAT from the system-node subnet. A Stage 3 static GO does not rule out this failure. Do not substitute a NAT public IP as the NVA next hop. |
| Stage 4 `Insufficient quota for VM size` | Not enough vCPU quota for the supercomputer system pool. Raise the named quota (Subscriptions > Usage + quotas, or `az quota update`), then re-run Stage 4. |
| Stage 4 partial / stranded resource | Re-run (state is detected and resumed); use `-Recovery` to re-PUT the stranded resource. |
