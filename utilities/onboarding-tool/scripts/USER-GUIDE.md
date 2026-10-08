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
3. **Permissions** on the target subscription / resource group:
   - Stage 2 creates **role assignments**, so you need **Owner**, **User Access Administrator**, or
     **RBAC Administrator** at the target scope.
   - Stage 4 creates platform resources, so you need rights to deploy into the target resource group.
4. **A resource group** for the platform (Stage 4 deploys into it). Create it if needed:
   ```powershell
   az group create -n <your-rg> -l <region>
   ```
5. **A user-assigned managed identity (UAMI)** — **required for Stage 4**. The tool does **not**
   create this for you; you must pre-create it and record its resource id in the config
   (`managedIdentity.id`). Create one with:
   ```powershell
   az identity create -g <your-rg> -n <your-uami-name> --query id -o tsv
   ```
   Copy the printed resource id; you will put it in the planning form / config.

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
| `deployingIdentity.objectId` | The identity that will deploy (Stage 2 grants it the platform roles). Enter the Entra **objectId (GUID)**, or — if you don't know it — an **email/UPN** of a user in the target tenant (or an app registration's appId/display name). Stage 1 resolves a non-GUID value to the objectId via `az` (run `az login` first). Find your own objectId with `az ad signed-in-user show --query id -o tsv`. |
| `resourceGroup` | The platform resource group from step 2.4. |
| `managedIdentity.id` | The UAMI resource id from step 2.5 (used by Stage 4). |
| `controlPlaneRegion` / `workloadRegion` | The Azure region(s) to deploy into. Use a region known to support `Microsoft.Discovery/supercomputers` — **`eastus`** is confirmed; some regions (e.g. `eastus2`, `uksouth`) have rejected supercomputer creation. |
| `names.*` | The resource names (workspace, project, supercomputer, node pool, etc.). Keep them unique in the subscription. |

Notes:
- **Policies are collected live** from the subscription at runtime — you do not list deny/audit
  policies in the form. Add a `POLICY` row only to declare or override one.
- For the **BYO** form, `controlPlaneRegion` must equal the region of the existing VNet that holds
  the `managedcluster` / `nodepool` subnets.

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

### Stage 2 — Prepare the landing zone (writes resources)

**Scope:** **writes to Azure.** Registers resource providers, assigns RBAC roles, and provisions
networking in the target subscription / resource group. Run against the intended subscription only.

```powershell
./stage2-landing-zone/stage2_prepare.ps1 -ConfigPath ./config.json -JsonPath ./out/stage2.json
```

- Registers resource providers, assigns RBAC, creates the one-time NSP Perimeter Joiner role, and
  (for managed / byo-spoke / greenfield network models) provisions the VNet, subnets with the
  required delegations, shared NSG allow-list, route tables, and private DNS zones.
- Also emits firewall-request and quota-exemption artifacts under `./out/` (hand these to your
  network/governance team if required).
- **Idempotent** — safe to re-run; it stops on the first hard failure with its remediation.

> This stage writes to Azure. Make sure you are pointed at the intended subscription
> (`az account show`).

### Stage 3 — Validate readiness (read-only)

**Scope:** read-only control-plane checks. The only thing it can create is the optional `-WithVm`
probe VM, which is always torn down — and that option is currently disabled (see below), so a plain
run writes nothing.

```powershell
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile workspace -JsonPath ./out/stage3.json
```

- Read-only gate before deployment: subnet delegation, effective NSG rules, effective routes, DNS
  and private-endpoint resolution.
- `-Profile` selects the check set: `supercomputer` (default), `workspace`, or `bookshelf`.
- **Leave `-WithVm` off.** The in-network probe VM is temporarily disabled: `az vm create` trips an
  empty-arg binding issue (`--public-ip-address ''` / `--nsg ''`), so the ephemeral VM and its
  in-network probes (DNS, TCP 443, HTTPS/artifact, PE resolution, east-west 10250) are skipped. The
  control-plane checks above still run and are sufficient to gate deployment.

### Stage 4 — Deploy the platform (writes resources)

**Scope:** **writes to Azure.** Creates the Discovery platform resources in the target resource
group. Re-runnable: it detects real resource state and resumes from the first incomplete resource.

```powershell
./stage4-deployment/stage4_deploy.ps1 -ConfigPath ./config.json -JsonPath ./out/stage4.json
```

- Deploys in dependency order: **supercomputer → workspace → chatModel → project → bookshelf
  storage container** (Discovery api-version `2026-06-01`), via `discovery-platform.bicep`.
- Detects real resource state before each step, so a re-run **resumes** from the first incomplete
  resource. Use `-Recovery` to re-PUT a stranded resource.
- **Supercomputer creation includes AKS provisioning and can take 15–30 minutes.** Be patient.
- Requires the Stage 4 config fields: `resourceGroup`, `managedIdentity.id` (your pre-created UAMI),
  and `storage`.

**Region caveat:** if the supercomputer deployment returns an `InternalServerError` with a
correlation id, the region likely does not support supercomputer creation. Re-run against a
confirmed region such as **`eastus`** (update `controlPlaneRegion`/`workloadRegion` in the form,
re-run Stage 1 to regenerate `config.json`, then Stage 4).

### Stage 5 — Enable and certify a scenario (creates one agent)

**Scope:** **writes to Azure** — one Discovery agent (`scientistQnAAgent`) plus a throw-away
investigation/conversation used for the test. No tool is created. Must run from a network that can
reach the platform private endpoint.

```powershell
./stage5-scenario-enablement/stage5_enable.ps1 -ConfigPath ./config.json -JsonPath ./out/stage5.json
```

- Confirms platform private-endpoint DNS + 443 reachability, then creates a Discovery agent named
  **`scientistQnAAgent`** (no tool bound), opens an investigation + conversation, sends a scientific
  Q&A prompt, and verifies the agent returns a **completed, non-empty answer**.
- **Must run from a network that can reach the platform private endpoint** — inside the VNet, or a
  peered/allowed network. From an unconnected machine the connectivity check fails first (by design).
- Override the prompt with `-Prompt "<your question>"` if you want to test a different question.

---

## 6. Reading the results

- **Verdict line:** each stage ends with `GO` (exit `0`) or `NO-GO` (non-zero). Only a `GO` lets you
  advance.
- **Per-check rows:** every check shows Pass / Fail / Warn / Skip. **Every failure carries an exact
  remediation string** — read it; it tells you what to change.
- **JSON reports:** `./out/stage1.json … stage5.json` are the machine-readable equivalents, good for
  records or pipeline gating.
- **Artifacts:** Stage 2 writes firewall-request / quota-exemption / policy-exemption markdown under
  `./out/` for the teams that own those approvals.

---

## 7. Common issues and fixes

| Symptom | Fix |
|---|---|
| Stage 1 won't write `config.json` | One or more required checks failed. Fix the flagged yellow cell (or add a `WAIVER`/`POLICY` row), then re-run. |
| "Not logged in" / Az checks skipped | `az login` and `az account set --subscription <id>`, then re-run. |
| Stage 2 RBAC failure | You lack role-assignment rights. Get **Owner / User Access Administrator / RBAC Administrator** at the scope. |
| Stage 4 fails on `managedIdentity` | `managedIdentity.id` is missing or wrong. Pre-create the UAMI (step 2.5) and set its resource id in the form, re-run Stage 1, then Stage 4. |
| Stage 4 supercomputer `InternalServerError` | Region likely unsupported for supercomputers. Switch to **`eastus`** (or another confirmed region), re-run Stage 1, then Stage 4. |
| Stage 4 partial / stranded resource | Re-run (state is detected and resumed); use `-Recovery` to re-PUT the stranded resource. |
| Stage 5 connectivity check fails | You are not on a network that can reach the platform private endpoint. Run from inside the VNet or a peered/allowed network. |

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
./stage3-validation/stage3_validate.ps1 -ConfigPath ./config.json -Profile workspace -JsonPath ./out/stage3.json
# 4. Deploy (15–30 min for the supercomputer)
./stage4-deployment/stage4_deploy.ps1 -ConfigPath ./config.json -JsonPath ./out/stage4.json
# 5. Certify a Q&A agent
./stage5-scenario-enablement/stage5_enable.ps1 -ConfigPath ./config.json -JsonPath ./out/stage5.json
```

When Stage 5 prints `GO`, your Discovery environment is deployed and a `scientistQnAAgent` has
answered a live prompt end to end.
