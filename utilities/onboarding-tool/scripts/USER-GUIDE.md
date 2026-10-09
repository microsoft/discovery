# Microsoft Discovery onboarding — user guide

This guide walks you, step by step, through using the onboarding tool to **prepare**, **validate**,
and **deploy** the Azure resources for a Microsoft Discovery environment. It is written for the
operator who will actually run the scripts. Follow it top to bottom the first time; after that you
can jump straight to [The five stages](#the-five-stages). Everything you need is in this document —
no other files are required reading.

---

## 1. What the tool does

The tool is a **five-stage pipeline**. Each stage is one PowerShell script. You run them in order,
and each one either prints a green **GO** verdict and exits `0`, or prints a red **NO-GO** verdict
with an exact remediation string and exits non-zero.

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

Install and sign in once:

1. **PowerShell 7+** — every script declares `#Requires -Version 7.0`.
   ```powershell
   pwsh --version   # expect 7.x
   ```
2. **Azure CLI**, logged in to the subscription you will deploy into:
   ```powershell
   az login
   az account set --subscription <your-subscription-id>
   az account show --query '{name:name, id:id}' -o table
   ```
3. **Permissions** at subscription scope: **Owner**, or **Contributor** plus **User Access
   Administrator** or **RBAC Administrator**. Stage 2 registers providers and creates resource
   groups, the VNet, and the storage account (Contributor), and it creates role assignments
   (User Access Administrator or RBAC Administrator). Either role alone isn't enough.
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
7. **Compute and model quota** in the deployment region. The supercomputer's system pool runs 3 ×
   `Standard_D4s_v6` (12 vCPUs) and is checked when you submit, so you need at least **12 free Total
   Regional vCPUs and 12 free Standard DSv6 Family vCPUs**. The node pool can scale out to 3 ×
   `Standard_D4ds_v6` (12 more vCPUs, DDSv6 Family). Check with
   `az vm list-usage -l <region> -o table`. Each workspace also uses 450K GPT-5.4 GlobalStandard
   TPM (250K for the built-in deployment plus 200K for the validation chat model). GlobalStandard
   quota is shared across all regions in the subscription. Stage 1 checks vCPU and TPM quota, and
   Stage 3 re-checks them before Stage 4. AI Search capacity for Bookshelf isn't checked.

> `ImportExcel` is **not** required. Stage 1 reads `.xlsx` forms natively.

---

## 3. Choose your network model and planning form

There are **two** planning forms. Pick the one that matches how the VNet is provided:

- **Managed VNet** — the tool provisions the VNet for you:
  `stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx`
- **BYO (bring-your-own) existing VNet** — you pre-created the VNet; the tool validates it:
  `stage1-planning/discovery-resource-planning-form-byo-vnet.xlsx`

Open the form, go to the **`Config`** sheet, and fill in every **yellow Value cell**. The form is
organized into sections (identity & subscription, regions, network, storage, sizing, names, etc.).
Notes next to each field explain what to enter. A few that trip people up:

| Field | What to enter |
|---|---|
| `subscriptionId` | The subscription you ran `az account set` against. |
| `deployingIdentity.objectId` | The identity that will deploy. If `principals` is empty, Stage 2 grants it the Discovery roles plus the Azure roles a Discovery administrator needs (Managed Identity Contributor and Operator, Storage Account Contributor, Storage Blob Data Contributor, Network Contributor, AcrPush) on the target resource groups, and Stage 4 grants it Foundry User on the workspace managed resource group. Enter the Entra **objectId (GUID)**, or — if you don't know it — an **email/UPN** of a user in the target tenant (or an app registration's appId/display name). Stage 1 resolves a non-GUID value to the objectId via `az` (run `az login` first). Find your own objectId with `az ad signed-in-user show --query id -o tsv`. |
| `resourceGroup` | The platform resource group from prerequisite 5. |
| `managedIdentity.id` | The UAMI resource id from prerequisite 6 (used by Stage 4). |
| `network.networkResourceGroup` | The resource group that holds (managed: will hold) the VNet. Can be the platform RG or a separate network RG; it must exist before Stage 2. |
| `network.vnetName` | **Managed form:** optional — leave blank and the tool names the VNet `vnet-<names.workspace>`. **BYO form:** the name of your **existing** VNet in `network.networkResourceGroup` (Stage 1 checks it exists and is in `controlPlaneRegion`). |
| `controlPlaneRegion` / `workloadRegion` | Use a supported production region: **East US**, **Sweden Central**, or **UK South**. Keep resources for one deployment in the same region unless an approved architecture requires otherwise. |
| `names.*` | The resource names (workspace, project, supercomputer, node pool, etc.). Keep them unique in the subscription. |
| `storage.account` | Required for every project, independently of Bookshelf. Use a globally unique storage account name and keep `storage.model=byo`; Stage 2 creates the account, required Blob CORS rules, and private endpoint if it does not exist. The account denies public network traffic, so users who open project outputs in Discovery Studio need network access to it: from the VNet (VPN or ExpressRoute), or through a client IP rule you add. |
| `workspace.publicNetworkAccess` | `Enabled` (default) or `Disabled`. With `Disabled`, the workspace data plane (agents, investigations, conversations) answers only from inside the VNet, so Stage 5 must run from a runner with private network access. |
| `workspace.networkIsolation` | `true` (default) isolates the Workbench and requires VPN or ExpressRoute to the workspace VNet. `false` enables authenticated public Workbench access. This setting is independent of `workspace.publicNetworkAccess`. |

Notes:
- **Policies are collected live** from the subscription at runtime — you do not list deny/audit
  policies in the form. Add a `POLICY` row only to declare or override one.
- For the **BYO** form, `controlPlaneRegion` must equal the region of the existing VNet that holds
  the `managedcluster` / `nodepool` subnets.
- For the BYO form, the tool doesn't change your VNet. Before Stage 3, make sure that:
  - Each SUBNET row's CIDR matches an existing subnet. Stage 1 maps rows to subnet names by CIDR
    and fails `byo-subnets` on a mismatch.
  - The workspace, agent and search subnets are delegated to `Microsoft.App/environments`, and the
    management subnet to `Microsoft.ContainerService/managedClusters`.
  - The `privatelink.*` zones listed under `privateDnsZones` in
    `stage3-validation/dependency-spec.json` exist in `network.dnsResourceGroup` (or the network
    RG) and are linked to the VNet. Stage 2 creates only the blob zone, for the Bookshelf private
    endpoint. Stage 3 prints the create and link commands for any missing zone.
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

```powershell
./stage2-landing-zone/stage2_prepare.ps1 -ConfigPath ./config.json -JsonPath ./out/stage2.json
```

- Registers resource providers, assigns RBAC, creates the one-time NSP Perimeter Joiner role,
  assigns both that role and **Reader** to the Discovery control-plane service principal, and
  (for managed / byo-spoke / greenfield network models) provisions the VNet, subnets with the
  required delegations, shared NSG allow-list, route tables, and private DNS zones.
- RBAC covers the Discovery roles and the administrator's Azure roles on the target resource
  groups, plus the UAMI roles from prerequisite 6 after the network and storage exist.
- Also emits firewall-request, quota-increase-request, and policy-exemption-request files next to
  `-JsonPath` (`./out/`); hand these to your network/governance team if required.
- **Idempotent** — safe to re-run; it stops on the first hard failure with its remediation.

> This stage writes to Azure. Make sure you are pointed at the intended subscription
> (`az account show`).

### Stage 3 — Validate readiness (read-only)

**Scope:** read-only control-plane checks. The only thing it can create is the optional `-WithVm`
probe VM, which is always torn down — and that option is currently disabled (see below), so a plain
run writes nothing.

```powershell
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile supercomputer -JsonPath ./out/stage3-supercomputer.json
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile workspace     -JsonPath ./out/stage3-workspace.json
```

- Read-only gate before deployment: subnet delegation, effective NSG rules, effective routes, DNS
  and private-endpoint resolution.
- `-Profile` selects the check set: `supercomputer` (default), `workspace`, or `bookshelf`. Run
  **both `supercomputer` and `workspace`**: Stage 4 deploys both, and each profile checks only its
  own subnets (supercomputer: managedcluster, nodepool, spare; workspace: container-app and
  private-endpoint subnets).
- **Leave `-WithVm` off.** The in-network probe VM is temporarily disabled: `az vm create` trips an
  empty-arg binding issue (`--public-ip-address ''` / `--nsg ''`), so the ephemeral VM and its
  in-network probes (DNS, TCP 443, HTTPS/artifact, PE resolution, east-west 10250) are skipped. The
  control-plane checks above still run and are sufficient to gate deployment.

### Stage 4 — Deploy the platform (writes resources)

**Scope:** **writes to Azure.** Creates the Discovery platform resources in the target resource
group. Re-runnable: it detects real resource state and resumes from the first incomplete resource.

```powershell
./stage4-deployment/stage4_deploy.ps1 -ConfigPath ./config.json -ReadinessReport ./out/stage3-supercomputer.json,./out/stage3-workspace.json -JsonPath ./out/stage4.json
```

- `-ReadinessReport` takes one or more Stage 3 reports (comma-separated); Stage 4 refuses to write
  unless every one is `GO`, and warns if none covers the `supercomputer` profile.
  Without it, Stage 4 still runs but flags the missing gate as a warning.
- Deploys in dependency order: **supercomputer → workspace → chatModel → project storage
  container → project** (and Bookshelf-specific resources when in scope), using Discovery
  api-version `2026-06-01` via `discovery-platform.bicep`.
- Detects real resource state before each step, so a re-run **resumes** from the first incomplete
  resource. Use `-Recovery` to re-PUT a stranded resource.
- After the project, assigns **Foundry User** on the workspace managed resource group (to
  `principals` with a Platform Administrator or Contributor role, else `deployingIdentity`) so they
  can edit agents and workflows in the Foundry portal. A failure here is a warning.
- **Supercomputer creation includes AKS provisioning and can take 15–30 minutes.** Be patient.
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
| 2 | `stage2.md`, `stage2.json`, `firewall-request-<workspace>.md/.json`, `quota-increase-requests-<workspace>.md/.json`, `policy-exemption-requests-<workspace>.md/.json` | Verdict is GO. Hand each request file to the owning team (network, quota, governance) and wait for approval before Stage 3. A request file with an empty list means nothing needs approval. |
| 3 | `stage3-supercomputer.md/.json`, `stage3-workspace.md/.json` | Both reports are GO. Check subnet delegation, NSG, and route rows; Skip rows must give a reason. Stage 4 reads these `.json` files through `-ReadinessReport`. |
| 4 | `stage4.md`, `stage4.json` | Verdict is GO and every resource (supercomputer, node pool, workspace, chat model, project, Bookshelf if in scope) shows Succeeded with its resource id. On failure, the report includes the ARM error and remediation. |
| 5 | `stage5.md`, `stage5.json`, `stage5-response-<timestamp>.json`, `stage5-state-<timestamp>.json` | Verdict is GO. The response file holds the agent's answer; confirm it is `completed` and the text answers the prompt. The state file records the agent, investigation, and conversation used by the test. |

---

## 7. Common issues and fixes

| Symptom | Fix |
|---|---|
| Stage 1 won't write `config.json` | One or more required checks failed. Fix the flagged yellow cell (or add a `WAIVER`/`POLICY` row), then re-run. |
| "Not logged in" / Az checks skipped | `az login` and `az account set --subscription <id>`, then re-run. |
| Stage 2 RBAC failure | You lack role-assignment rights. Get **Owner**, or **Contributor** plus **User Access Administrator / RBAC Administrator**, at subscription scope. |
| Stage 4 fails on `managedIdentity` | `managedIdentity.id` is missing or wrong. Pre-create the UAMI (prerequisite 6) and set its resource id in the form, re-run Stage 1, then Stage 4. |
| Stage 4 fails `managed identity role assignments` | The UAMI is missing a required role. Run the `az role assignment create` commands printed in the report, wait 5–10 minutes, then re-run Stage 4. |
| Stage 4 fails `supercomputer subnet topology` | The `aksSubnet` is delegated, or `UserDefinedRouting` has no delegated `managementSubnet`. Run the `az network vnet subnet update` command printed in the report, re-run Stage 3, then Stage 4. |
| Stage 4 supercomputer `InternalServerError` | Check the subnet-topology and UAMI-role checks first (see the Stage 4 caveat). Delete the Failed supercomputer, then re-run. If both pass, open a support case with the correlation id. |
| Stage 4 `Insufficient quota for VM size` | Not enough vCPU quota for the supercomputer system pool. Raise the named quota (Subscriptions > Usage + quotas, or `az quota update`), then re-run Stage 4. |
| Stage 4 partial / stranded resource | Re-run (state is detected and resumed); use `-Recovery` to re-PUT the stranded resource. |

---

## 8. Quick end-to-end recap

```powershell
cd utilities/onboarding-tool/scripts
az login; az account set --subscription <id>

# 1. Plan
./stage1-planning/stage1_plan.ps1 -FormPath ./stage1-planning/discovery-resource-planning-form-managed-vnet.xlsx -OutConfig ./config.json -JsonPath ./out/stage1.json
# 2. Landing zone
./stage2-landing-zone/stage2_prepare.ps1 -ConfigPath ./config.json -JsonPath ./out/stage2.json
# 3. Validate
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile supercomputer -JsonPath ./out/stage3-supercomputer.json
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile workspace -JsonPath ./out/stage3-workspace.json
# 4. Deploy (15–30 min for the supercomputer); gated on the Stage 3 GO reports
./stage4-deployment/stage4_deploy.ps1 -ConfigPath ./config.json -ReadinessReport ./out/stage3-supercomputer.json,./out/stage3-workspace.json -JsonPath ./out/stage4.json
# 5. Certify a Q&A agent
./stage5-scenario-enablement/stage5_enable.ps1 -ConfigPath ./config.json -JsonPath ./out/stage5.json
```

When Stage 5 prints `GO`, your Discovery environment is deployed and a `scientistQnAAgent` has
answered a live prompt end to end.
