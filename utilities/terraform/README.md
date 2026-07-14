---
title: Deploy Microsoft Discovery with Terraform (AzureRM + AzAPI)
description: Terraform module for Microsoft Discovery, using AzureRM for platform primitives and AzAPI for Microsoft.Discovery/* resources.
ms.topic: quickstart
keywords:
  - terraform
  - azapi
  - azurerm
  - microsoft-discovery
  - quickstart
---

# Terraform utility: Deploy Microsoft Discovery

This utility is a minimal, end-to-end Terraform module for a Microsoft Discovery services environment. It uses the AzureRM provider for platform primitives (VNet, UAMI, storage, role assignments) and the AzAPI provider — pinned to API version `2026-02-01-preview` — for every `Microsoft.Discovery/*` resource.

The provider split is deliberate: `Microsoft.Discovery/*` is not yet in the AzureRM provider's resource catalog, so AzAPI is required for those types. Every other resource uses AzureRM to benefit from strongly-typed schemas, better plan output, and stable state migrations.

## Quickstart (TL;DR)

For an experienced Azure/Terraform user with an active `az login`, the full happy path is:

```bash
# 1. create the RG (kept out of Terraform state on purpose)
az group create --name rg-discovery-terraform --location swedencentral

# 2. grant yourself blob data access on the RG (see Step 6.1 for why)
MY_OID=$(az ad signed-in-user show --query id -o tsv)
SUB_ID=$(az account show --query id -o tsv)
az role assignment create --assignee "$MY_OID" \
  --role "Storage Blob Data Owner" \
  --scope "/subscriptions/$SUB_ID/resourceGroups/rg-discovery-terraform"

# 3. clone / cd into this directory, then preflight
cd utilities/terraform
cp -n terraform.tfvars.example terraform.tfvars   # edit if you want non-defaults
./preflight.sh                                    # 9 checks; exits non-zero on any FAIL

# 4. init / plan / apply
terraform init
terraform plan  -out=tfplan
terraform apply tfplan
```

Wall time is ~20-45 minutes, dominated by the supercomputer + workspace creates. The rest of this document walks through every step in detail and covers failure modes to expect.

## What you build

A single resource group containing:

* A virtual network with five subnets (two delegated to `Microsoft.App/environments`).
* A user-assigned managed identity with three role assignments.
* A storage account plus a blob container that Discovery mounts.
* A Discovery Supercomputer with one Node Pool.
* A Discovery Workspace with one Chat Model Deployment.
* A Discovery Storage Container bound to the storage account above.
* A Discovery Project inside the workspace.

Estimated wall time: 20 to 30 minutes for the first run, most of it waiting on the Supercomputer to come up.

## Prerequisites

Local tooling:

* Azure CLI 2.60 or later.
* Terraform 1.9 or later.
* A shell with `jq` available (optional but helpful).

Azure requirements (verified in Step 1 below):

* An Azure subscription in a tenant where you can sign in with `az login`.
* Permission to create resources and role assignments in that subscription. `Owner` or the combination of `Contributor` plus `Role Based Access Control Administrator` at subscription scope both work. Plain `Contributor` will fail on the three role assignments the module creates.
* The `Microsoft.Discovery`, `Microsoft.Network`, `Microsoft.ManagedIdentity`, `Microsoft.Storage`, `Microsoft.Authorization`, and `Microsoft.App` resource providers registered on the subscription.
* Deployment region set to one of the Discovery-supported regions: `eastus`, `eastus2`, `uksouth`, or `swedencentral`.

## Step 1: Sign in and verify permissions

### 1.1 Sign in

```bash
az login
az account set --subscription "<subscription-name-or-id>"
```

Confirm the active context:

```bash
az account show --output json
```

You should see the subscription you intend to deploy into as `isDefault: true`, plus the user and tenant you expect.

### 1.2 Check RBAC on the subscription

```bash
MY_OID=$(az ad signed-in-user show --query id -o tsv)

az role assignment list \
  --assignee "$MY_OID" \
  --include-inherited \
  --query "[].{role:roleDefinitionName, scope:scope}" \
  -o table
```

Look for one of:

* `Owner` scoped to `/subscriptions/<sub-id>`.
* `Contributor` **and** `Role Based Access Control Administrator` (or `User Access Administrator`), either at subscription scope or at a management group above it.

If you only see `Contributor`, the deployment will fail at the three `azurerm_role_assignment` blocks with `AuthorizationFailed`. Ask an Owner to grant you `Role Based Access Control Administrator` at the subscription scope before continuing.

### 1.3 Check resource provider registration

Discovery depends on 25 resource providers. Rather than list them all here, let the preflight script check them for you — it verifies `Microsoft.Discovery` plus the 24 dependency RPs and prints the exact `az provider register` command for any that aren't registered:

```bash
cd utilities/terraform
./preflight.sh          # checks 1 and 5 cover RP registration
```

If you'd rather spot-check the critical few manually first:

```bash
for ns in \
  Microsoft.Discovery \
  Microsoft.Network \
  Microsoft.ManagedIdentity \
  Microsoft.Storage \
  Microsoft.Authorization \
  Microsoft.App
do
  az provider show -n "$ns" \
    --query "{namespace:namespace, state:registrationState}" -o tsv
done
```

Every namespace should report `Registered`. To register any that are not:

```bash
az provider register --namespace <namespace> --wait
```

`Microsoft.Discovery` in particular has a several-minute registration time on first use in a fresh subscription.

### 1.4 Pick a region

List regions the Discovery RP claims to support:

```bash
az provider show -n Microsoft.Discovery \
  --query "resourceTypes[?resourceType=='workspaces'].locations[]" -o tsv
```

> **Region availability as of 2026-07-10** (verified against real `terraform apply` attempts on subscription
> `ME-MngEnvMCAP385978-ossiottka-1`). The RP-metadata list above is not authoritative on its own — several
> regions advertise support but fail creates for other reasons. Cross-check against this table before
> committing to a region:
>
> | Region | Status | Failure mode if broken |
> |---|---|---|
> | `uksouth` | ✅ **recommended** | — |
> | `swedencentral` | ⚠️ use with fallback | Hit `AKSCapacityHeavyUsage` on 2026-07-09; likely transient but not queryable in advance |
> | `eastus` | ❌ avoid unless SKU is allowlisted | Subscription-level: all `Standard_D4s_v*` SKUs return `NotAvailableForSubscription`. The Discovery RP internally provisions AKS with `Standard_D4s_v6`, so the SC create is rejected. Fix requires an Azure support ticket to enable D-series compute in this region. |
> | `eastus2` | ❌ avoid | Discovery RP **region gate**: metadata claims support, but the PUT handler rejects new supercomputer creates with `"Creation of new Supercomputer resources is not supported in region 'eastus2'"`. Not transient — will fail every attempt until Microsoft ships an RP update. Re-check this note periodically. |
>
> The `preflight.sh` script (Step 6.4) checks the deterministic failure modes (registration, SKU
> availability, quota) automatically. The RP region gate on `eastus2` cannot be detected via any
> Azure API today — that's why it lives in this table instead of the script.

### 1.5 Record what you found

Before moving on, capture these values somewhere handy (a scratch file, `~/.discovery-env`, or your shell history):

| Value | Example |
|-------|---------|
| Subscription ID | `00000000-0000-0000-0000-000000000000` |
| Tenant ID | `00000000-0000-0000-0000-000000000000` |
| Signed-in user object ID | `00000000-0000-0000-0000-000000000000` |
| Target region | `uksouth` |

Terraform will pull the first three from your `az` context automatically, but keeping them written down makes debugging RBAC errors much faster.

## Step 2: Create the resource group

Terraform can create a resource group for you (via `azurerm_resource_group`), but keeping the RG out of Terraform state has two practical benefits:

* A `terraform destroy` mistake cannot wipe the RG (and anything else living in it that you might add later, like manual Studio uploads).
* The RG's lifecycle is often owned by a platform team separate from whoever runs Terraform.

So we create the RG imperatively with `az` and pass its name to Terraform as a variable. If your organization prefers Terraform-managed RGs, swap this step for an `azurerm_resource_group` resource in Step 3 — nothing else in the module changes.

### 2.1 Create the RG

```bash
az group create \
  --name rg-discovery-terraform \
  --location uksouth \
  --output table
```

Expected output:

```text
Location    Name
----------  ----------------------
uksouth     rg-discovery-terraform
```

### 2.2 Confirm it exists and is empty

```bash
az group show --name rg-discovery-terraform --query "{name:name, location:location, state:properties.provisioningState}" -o table
az resource list --resource-group rg-discovery-terraform -o table
```

The second command should return an empty result. You are now ready to lay down the Terraform project in Step 3.

### 2.3 Record the RG name

Add it to the scratch list from Step 1.5:

| Value | This quickstart's example |
|-------|---------------------------|
| Resource group | `rg-discovery-terraform` |
| Region | `uksouth` |

## Step 3: Scaffold the Terraform project

Every file below lives in the same directory as this quickstart (`Terraform/`). Run `ls Terraform/` after this step and you should see:

```text
.gitignore
README.md
discovery.tf           # written in Step 5
identity.tf            # written in Step 4
locals.tf
network.tf             # written in Step 4
outputs.tf
providers.tf
roles.tf               # written in Step 4
storage.tf             # written in Step 4
terraform.tfvars.example
variables.tf
```

### 3.1 `providers.tf` -- pin both providers

The module uses two providers on purpose. This is the single most important architectural choice in the utility, so it deserves a file of its own:

* **`azurerm ~> 4.20`** for every non-Discovery resource (VNet, subnets, UAMI, storage account, blob CORS, role assignments).
* **`azapi ~> 2.0`** for every `Microsoft.Discovery/*` resource, plus the single blob container that would otherwise require Storage data-plane rights. There is no `azurerm_discovery_*` resource in AzureRM today; AzAPI talks to the ARM REST API at a pinned version. We pin **`2026-02-01-preview`**, which matches what AzAPI v2.10 ships schemas for at time of writing.

See [providers.tf](providers.tf) for the exact block. Note the two commented-out lines you may want to enable later:

* `storage_use_azuread = true` on the `azurerm` provider -- only if you swap the AzAPI blob container in Step 4 for a plain `azurerm_storage_container`.
* `enable_preflight = true` on the `azapi` provider -- turns on plan-time schema validation for every AzAPI resource. Highly recommended once you get past the first apply.

### 3.2 `variables.tf` and `locals.tf` -- input contract

[variables.tf](variables.tf) declares every input the module accepts, including the same constraints Discovery requires (subnet CIDRs, node-pool VM SKU, node counts, chat model name). Defaults are pre-filled with sensible starter values so a `terraform apply` with no `-var` overrides produces a working environment.

[locals.tf](locals.tf) does two things:

* Declares a `random_string` for an 8-character suffix. Any resource name left unset in `tfvars` derives from this suffix.
* Reads the resource group (created in Step 2) via `data "azurerm_resource_group" "rg"`. We deliberately do NOT manage the RG in Terraform -- keeping it imperative protects it from `terraform destroy`.

### 3.3 `outputs.tf` -- resource IDs for downstream automation

[outputs.tf](outputs.tf) exports nine resource IDs (supercomputer, node pool, workspace, chat model deployment, Discovery storage container, project, UAMI, storage account, VNet) plus the UAMI's `principal_id` for anyone downstream who needs to grant it more roles.

### 3.4 `terraform.tfvars.example` and `.gitignore`

Copy [terraform.tfvars.example](terraform.tfvars.example) to `terraform.tfvars` and edit anything you want to pin. Everything commented out falls back to the defaults in `variables.tf`.

[.gitignore](.gitignore) keeps state files, `.terraform/`, real `.tfvars`, and plan artifacts out of git.

### 3.5 Sanity check

```bash
cd Terraform
terraform fmt -check
terraform validate  # will fail until Steps 4 and 5 are written -- expected
```

`terraform fmt -check` should pass right now. `terraform validate` won't pass until Step 5 lands, because the outputs in `outputs.tf` reference resources that don't exist yet.

## Step 4: Author the platform primitives (AzureRM)

Every resource in this step is a stable AzureRM type. **No AzAPI here except one blob container** (called out explicitly in 4.3). If you see an AzAPI block outside of that, something drifted.

### 4.1 `network.tf` -- VNet + five subnets   [PROVIDER: azurerm]

[network.tf](network.tf) creates the VNet and five standalone `azurerm_subnet` blocks. Two subnets (`workspace`, `agent`) carry a `delegation { service_delegation { name = "Microsoft.App/environments" } }` because Discovery attaches Container Apps environments into them.

Why standalone `azurerm_subnet` rather than inline `subnet {}` blocks on `azurerm_virtual_network`: mixing the two styles is a well-known source of drift in AzureRM. Standalone is the recommended pattern and it lets each subnet have its own lifecycle.

Note that you don't need explicit `depends_on` blocks between the VNet and its subnets — Terraform infers ordering from `azurerm_subnet.aks.id` references elsewhere in the module.

### 4.2 `identity.tf` -- one user-assigned managed identity   [PROVIDER: azurerm]

[identity.tf](identity.tf) creates the shared UAMI that shows up in three places downstream:

* `Supercomputer.identities.clusterIdentity`, `kubeletIdentity`, `workloadIdentities`
* `Workspace.workspaceIdentity`
* All three role assignments in [roles.tf](roles.tf)

**Known gap.** Discovery expects `isolationScope: 'Regional'` on the UAMI (Managed Identity API `2024-11-30`). AzureRM 4.x does not yet expose this property. The file includes a code comment showing how to add an `azapi_update_resource` patch if your policy requires it. For a smoke test, the default is fine.

### 4.3 `storage.tf` -- storage account (AzureRM) + one blob container (**AzAPI**)

[storage.tf](storage.tf) is the one file in Step 4 that mixes both providers. The reasoning:

* **`azurerm_storage_account`** covers the account and folds blob-service CORS into a nested `blob_properties { cors_rule { ... } }` block. Clean, typed, done.
* **`azapi_resource` for the blob container** exists because we set `shared_access_key_enabled = false`. AzureRM's `azurerm_storage_container` talks to the Storage **data plane** and needs either shared keys or an Entra principal with `Storage Blob Data Owner` on the account. Neither is a great fit for CI/CD, so we talk to the **control plane** directly at `Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01` via AzAPI.

If you're running locally and already hold `Storage Blob Data Owner` on the account you're deploying into, you can swap the AzAPI block for a plain `azurerm_storage_container` and set `storage_use_azuread = true` on the AzureRM provider in `providers.tf`. Behaviour is identical from Discovery's perspective.

### 4.4 `roles.tf` -- three role assignments   [PROVIDER: azurerm]

[roles.tf](roles.tf) creates the three role assignments Discovery requires, all bound to the UAMI's `principal_id`:

| Role                             | Scope                | Definition ID |
|----------------------------------|----------------------|----------------|
| Storage Blob Data Contributor    | Storage account      | `ba92f5b4-...` |
| Discovery Platform Contributor   | Resource group       | `01288891-...` (Discovery-owned built-in; hardcode the GUID) |
| AcrPull                          | Resource group       | `7f951dda-...` |

Every assignment has `depends_on = [azurerm_user_assigned_identity.workspace]` to avoid the `PrincipalNotFoundError` race that hits when the UAMI's service principal has not fully replicated to Entra ID by the time the role assignment is submitted. Terraform's implicit dependency graph does not know about that lag; the explicit `depends_on` costs nothing and buys reliability.

### 4.5 Validate

```bash
cd Terraform
terraform fmt -check
terraform validate  # still fails until Step 5 -- expected
```

## Step 5: Author the Discovery resources (AzAPI)

**Every resource in [discovery.tf](discovery.tf) uses `azapi_resource`.** This is why the utility exists: AzureRM ships no `azurerm_discovery_*` resources today, and driving ARM PUTs through AzAPI is the only Terraform-native path to Discovery resources right now.

All six blocks pin `@2026-02-01-preview`. AzAPI v2.10 ships preview schemas for this version; when a GA schema becomes available in a future AzAPI release, the pin can move forward. Change it in one place per resource and note it in your commit message — schemas across API versions are close but not identical.

### 5.1 Supercomputer   [PROVIDER: azapi]

The trickiest line in the whole module lives here:

```hcl
workloadIdentities = {
  (azurerm_user_assigned_identity.workspace.id) = {}
}
```

That is HCL's syntax for a map with an interpolated key expression. The Discovery RP expects a dictionary keyed by the UAMI ARM ID, with an empty object as the value. Parentheses around the expression are mandatory. This is also the reason we chose azapi v2's HCL-native `body = { ... }` over `jsonencode(...)` — `jsonencode` cannot handle a computed key nicely.

### 5.2 Node pool   [PROVIDER: azapi]

Child of the Supercomputer via `parent_id = azapi_resource.supercomputer.id`. Straightforward — no surprises.

### 5.3 Workspace   [PROVIDER: azapi]

Two things worth flagging:

1. `workspaceIdentity` is a Discovery-specific identity block. It is **not** the standard ARM `identity` envelope. AzAPI passes it through unchanged; any future `azurerm_discovery_workspace` will have to model its own schema for this.
2. `tags = { version = "v2" }` is a schema-version pin the Discovery RP reads. Preserve it verbatim — do not treat it as a cosmetic tag.

Explicit `depends_on = [azurerm_role_assignment.discovery_platform_contributor]` because workspace create validates the UAMI has that role.

### 5.4 Chat model deployment   [PROVIDER: azapi]

Child of the workspace. The current schema exposes an optional `capacity` (min 1) for provisioned SKUs; left unset here to match the default consumption behavior.

### 5.5 Discovery StorageContainer   [PROVIDER: azapi]

This is the **control-plane binding** over an existing storage account -- it is NOT the blob container from Step 4.3. The `storageStore.storageAccountId` field points at the AzureRM-managed storage account, and Discovery attaches that account to the workspace.

Explicit `depends_on` on both the Storage Blob Data Contributor grant and the AzAPI blob container, since Discovery validates access via the UAMI at bind time.

### 5.6 Project   [PROVIDER: azapi]

Child of the workspace, references the Discovery StorageContainer.

### 5.7 Validate

```bash
cd Terraform
terraform fmt -check
terraform validate
```

Both should now pass. You are ready for `terraform init` in Step 6.

## Step 6: `terraform init`, `plan`, `apply`

### 6.1 Pre-apply: grant yourself a blob data role

Because `storage.tf` sets `shared_access_key_enabled = false` on the storage account, AzureRM's provider must poll the blob data plane with AAD (not shared keys) after creating it. That requires the identity running `terraform apply` to hold a blob data role on the account. Without this, apply fails with:

```text
Error: waiting for the Data Plane for Storage Account ... to become available:
  polling failed: executing request: unexpected status 403
  (403 Key based authentication is not permitted on this storage account.)
```

Grant yourself `Storage Blob Data Owner` at the RG scope **before** the first apply:

```bash
MY_OID=$(az ad signed-in-user show --query id -o tsv)
SUB_ID=$(az account show --query id -o tsv)

az role assignment create \
  --assignee "$MY_OID" \
  --role "Storage Blob Data Owner" \
  --scope "/subscriptions/$SUB_ID/resourceGroups/rg-discovery-terraform"
```

`Storage Blob Data Contributor` also works. Entra ID needs ~30 s to propagate the assignment; if apply still 403s immediately, wait a minute and re-run.

> Note: This is required because `providers.tf` sets `storage_use_azuread = true`. If you swap in a runner identity that already holds a blob data role at a higher scope (subscription/MG), you can skip this step.

### 6.2 Initialize the working directory

```bash
cd Terraform
terraform init
```

Expected output ends with:

```text
Terraform has been successfully initialized!
```

This downloads the three pinned providers (`hashicorp/azurerm ~> 4.20`, `Azure/azapi ~> 2.0`, `hashicorp/random ~> 3.6`) and writes `.terraform.lock.hcl`. Commit the lock file.

### 6.3 Format and validate

```bash
terraform fmt
terraform validate
```

Both should be silent (fmt) and print `Success! The configuration is valid.` (validate). If validate reports schema errors on the Discovery API version, see the header comment in `discovery.tf` — the pin is `@2026-02-01-preview` because AzAPI v2.10 doesn't yet ship a GA schema.

### 6.4 Preflight (recommended)

Before running `plan`, run `./preflight.sh` to catch the failure classes that only surface hours into an apply:

```bash
./preflight.sh                    # reads terraform.tfvars
./preflight.sh -l uksouth         # or override location
./preflight.sh -h                 # help + full arg list
```

The script runs 9 **deterministic** checks — things Azure will reject every time until you change your inputs or open a support ticket. Checks 1-4 are built into `preflight.sh`; checks 5-9 are encapsulated modules under [preflight-checks/](preflight-checks/) that can be individually disabled by removing their file.

| # | Check | Source |
|---|---|---|
| 1 | `Microsoft.Discovery` RP is Registered | `preflight.sh` |
| 2 | Region is not on the `KNOWN_BAD_REGIONS` blocklist (catches RP-level gates that no Azure API surfaces — e.g. `eastus2` rejects new supercomputer creates even though metadata claims support) | `preflight.sh` |
| 3 | AKS system-pool SKU (`Standard_D4s_v6`, hardcoded by the RP) and your `node_pool_vm_size` are both allowlisted on the subscription in the region (`NotAvailableForSubscription` is a hard block that only a support ticket can fix) | `preflight.sh` |
| 4 | Compute cores quota (family + regional total) is sufficient for `node_pool_max_node_count × vCPUs + AKS system pool` | `preflight.sh` |
| 5 | Registration state of the other 24 RPs Discovery depends on (Compute, Network, Storage, ManagedIdentity, CognitiveServices, DocumentDB, ContainerService, etc.) — prints ready-to-copy `az provider register` commands for any that are unregistered | [preflight-checks/05-additional-resource-providers.sh](preflight-checks/05-additional-resource-providers.sh) |
| 6 | Positive allowlist match against the Discovery-supported region list (`eastus`, `swedencentral`, `uksouth`) | [preflight-checks/06-approved-regions.sh](preflight-checks/06-approved-regions.sh) |
| 7 | `Microsoft.DocumentDB` (Cosmos DB) is available in the target region — otherwise workspace create fails its async Cosmos provisioning LRO | [preflight-checks/07-cosmosdb-region.sh](preflight-checks/07-cosmosdb-region.sh) |
| 8 | Chat model has enough AI Foundry TPM quota in the region (reads `chat_model_name` from `terraform.tfvars` / `variables.tf`; PASS ≥ recommended, WARN below recommended, FAIL at zero headroom) | [preflight-checks/08-ai-foundry-tpm.sh](preflight-checks/08-ai-foundry-tpm.sh) |
| 9 | **Opt-in.** Network Security Perimeter prerequisites (`AIFSPInfrastructure` SP + NSP Perimeter Joiner role + Reader). Skipped by default because this module deploys standard VNet-injected workspaces, not NSP-joined ones | [preflight-checks/09-network-security-perimeter.sh](preflight-checks/09-network-security-perimeter.sh) |

**Environment overrides:**

```bash
# Override the approved-regions allowlist (comma-separated) for check 6
PREFLIGHT_APPROVED_REGIONS="eastus,uksouth" ./preflight.sh

# Enable check 9 (only relevant if you extend the module to deploy
# network-hardened / NSP-joined workspaces)
PREFLIGHT_CHECK_NSP=1 ./preflight.sh
```

**Adding or removing checks.** Every file matching `preflight-checks/[0-9]*.sh` is auto-sourced in numeric order. To disable one, `rm` its file. To add one, drop a new numbered `.sh` in the same directory following the contract documented in [preflight-checks/README.md](preflight-checks/README.md). No changes to `preflight.sh` required.

**Provenance.** Checks 5-9 mirror the deterministic gates enforced by the Microsoft Discovery Toolbox VS Code extension (see [../discovery-toolbox/README.md](../discovery-toolbox/README.md)) — the checks that are (a) verifiable pre-`terraform apply` and (b) relevant to this Terraform module.

**Deliberately not checked** (would give false confidence):

- RP metadata region list — unreliable; check 2 (blocklist) + check 6 (allowlist) are the workarounds.
- Transient AKS capacity (`AKSCapacityHeavyUsage`) — not queryable in advance.
- Chat model catalog — no listable RP endpoint at `2026-02-01-preview`. Check 8 verifies quota for the *configured* model; verify the model name itself against the [Discovery docs](https://learn.microsoft.com/azure/microsoft-discovery/) manually.

Exit code is `0` if there are only `PASS`/`WARN` results, `1` on any `FAIL`. Don't run `terraform apply` until preflight is green.

### 6.5 Plan

```bash
cp -n terraform.tfvars.example terraform.tfvars   # first run only
terraform plan -out=tfplan
```

Expected shape:

```text
Plan: 19 to add, 0 to change, 0 to destroy.
```

The 19 resources are: `random_string.suffix`, `azurerm_virtual_network` + 5 subnets, `azurerm_user_assigned_identity`, `azurerm_storage_account`, `azapi_resource.outputs_container`, 3 `azurerm_role_assignment`, and 6 Discovery `azapi_resource`s (supercomputer, node pool, workspace, chat model, storage container, project). Ten outputs are also declared.

### 6.6 Apply

```bash
terraform apply "tfplan"
```

Wall time: **20–45 minutes**, dominated by the Discovery supercomputer (which provisions an AKS cluster + node pool) and the workspace. Both have `timeouts { create = "60m" }` set in `discovery.tf` to avoid spurious `context deadline exceeded` errors under RP load.

### 6.7 Known failure modes and recovery

**A. Workspace `context deadline exceeded` even with the 60m timeout.** The workspace is often provisioned server-side successfully by the time Terraform gives up. Check:

```bash
az resource list --resource-group rg-discovery-terraform \
  --query "[?type=='Microsoft.Discovery/workspaces'].{name:name, state:properties.provisioningState}" \
  -o table
```

If you see `Succeeded`, import it into Terraform state and re-plan:

```bash
SUB_ID=$(az account show --query id -o tsv)
WS_NAME=$(az resource list --resource-group rg-discovery-terraform \
  --resource-type Microsoft.Discovery/workspaces --query "[0].name" -o tsv)

terraform import azapi_resource.workspace \
  "/subscriptions/$SUB_ID/resourceGroups/rg-discovery-terraform/providers/Microsoft.Discovery/workspaces/$WS_NAME"

terraform plan -out=tfplan
terraform apply "tfplan"
```

Do the same for any child resource that also completed server-side (supercomputer, node_pool, etc.) — swap the resource type + Terraform address.

**B. Storage 403 on second apply.** Means the role assignment from Step 6.1 hasn't propagated. Wait 60 seconds, then re-run `terraform apply "tfplan"`. If it persists past 5 minutes, re-check the assignment:

```bash
az role assignment list --assignee "$MY_OID" \
  --scope "/subscriptions/$SUB_ID/resourceGroups/rg-discovery-terraform" \
  --query "[?roleDefinitionName=='Storage Blob Data Owner']" -o table
```

**C. `PrincipalNotFoundError` on the very first apply.** Entra ID replication race for the freshly-created UAMI. The `depends_on` entries in `roles.tf` mitigate this, but on cold subscriptions it can still lose. Re-run apply — no code changes needed.

## Step 7: (coming next) Verify the deployment in Discovery Studio

Placeholder. Log in to Discovery Studio, confirm the workspace and project appear, and run a smoke test.

## Step 8: (coming next) Tear down

Placeholder. `terraform destroy` sequence, plus `az group delete` if you want to remove the RG created in Step 2.

## Troubleshooting index

Filled in as each step lands. Common failure modes to preview:

* `AuthorizationFailed` on a role assignment — see Step 1.2.
* `KeyBasedAuthenticationNotPermitted` (storage 403) — see Step 6.1 and 6.6.B.
* `PrincipalNotFound` on first apply after UAMI creation — Entra ID replication race; see Step 6.6.C.
* `context deadline exceeded` on workspace — see Step 6.6.A (import path).
* `SubnetHasServiceEndpointConfiguration` or delegation conflicts — see Step 3.
* Discovery `workspace` create returning `InvalidRequest` with a `workspaceIdentity` error — the identity block is Discovery-specific, not the standard ARM `identity` envelope. See the `workspace` block in [discovery.tf](discovery.tf) for the correct shape.

## Deletion order:
Step 1: Delete the nodepool
Step 2: Delete the workspace
Step 3: Delete the supercomputer
Step 4: Delete the resource group


## TODO: Deleting the RG via the terraform.