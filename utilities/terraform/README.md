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

This utility provisions Microsoft Discovery services infrastructure with Terraform.
AzureRM manages platform resources (VNets, identities, storage accounts, and role
assignments); AzAPI manages `Microsoft.Discovery/*` resources using API version
`2026-06-01` and the blob container using the Storage ARM API. The `random`
provider supplies resource-name suffixes.

Terraform owns infrastructure lifecycle and state. Use [Discovery Toolbox](../discovery-toolbox/README.md)
for subscription readiness checks and subsequent agent/tool publishing. Bookshelf
remains supported as an optional Terraform-managed resource.

## Quickstart (TL;DR)

With an active `az login`, start from the repository root:

```bash
cd utilities/terraform
cp -n terraform.tfvars.example terraform.tfvars
```

Edit the copied values, then complete [Prerequisite validation](#prerequisite-validation).
The example uses `rg-discovery-terraform` and `uksouth` for both control-plane
resources and managed infrastructure. Match `RG_NAME` and `LOCATION` below to
`resource_group_name` and `location` in your configuration before running it.
Managed infrastructure follows `location` unless you explicitly set an override.

```bash
RG_NAME="rg-discovery-terraform"
LOCATION="uksouth"

# 1. create the RG (kept out of Terraform state on purpose)
az group create --name "$RG_NAME" --location "$LOCATION"

# 2. grant yourself blob data access on the RG (needed because the storage account disables shared keys)
MY_OID=$(az ad signed-in-user show --query id -o tsv)
SUB_ID=$(az account show --query id -o tsv)
export ARM_SUBSCRIPTION_ID="$SUB_ID"
az role assignment create --assignee "$MY_OID" \
  --role "Storage Blob Data Owner" \
  --scope "/subscriptions/$SUB_ID/resourceGroups/$RG_NAME"

# 3. init / validate / plan / apply
terraform init
terraform validate
terraform plan -out=deployment.tfplan
terraform apply deployment.tfplan
```

Provisioning can take over an hour, dominated by the supercomputer and workspace
creates. The logged validation run below took about 74 minutes for Terraform apply;
allow additional time for prerequisites, verification, and cleanup.

### Workspace user access

Subscription Owner or Contributor does not automatically grant Discovery
data-plane access. To allow users to load shared sessions and use the workspace,
set `workspace_contributor_principal_ids` in `terraform.tfvars`:

```hcl
workspace_contributor_principal_ids = [
  "00000000-0000-0000-0000-000000000001",
]
```

Use Entra user or group **object IDs in the deployment tenant**, not application
IDs or guest users' home-tenant IDs. Prefer a security group. The default is empty;
the deployer receives no automatic access. Each configured principal receives
Microsoft Discovery Platform Contributor at the workspace scope only. This
does not grant access to sibling tools or supercomputers, or to separate storage,
Foundry, or Bookshelf resources. It is not a complete Scientist-persona setup.
In the logged compute test below, submission initially returned HTTP 403 and
succeeded after a separate, approved resource-group-scoped Discovery Platform
Contributor grant. Review the
[persona role-assignment guidance](../rbac-roles-assignment/README.md) for broader
access requirements; this option does not automatically broaden user access.
Allow time for role propagation and sign out/in to Discovery after assignment.

If the same assignment already exists outside Terraform, configure its principal
ID and import the existing role assignment before applying. With the correct
Terraform workspace selected, the PowerShell command is:

```powershell
terraform import 'azurerm_role_assignment.workspace_contributor[\"<principal-object-id>\"]' '<existing-role-assignment-resource-id>'
```

Replace both placeholders. The import ID must be the full ARM resource ID of the
existing role assignment, not the role definition or Discovery workspace ID.
Do not delete a working assignment just to recreate it through Terraform.

## What you build

One resource group containing:

* Two peered VNets (workspace + supercomputer) with six subnets, four user-assigned identities with eight least-privilege role assignments, and a storage account with a blob private endpoint.
* A Discovery **Supercomputer** (+ node pool), **Workspace** (+ chat model + project), and a **Storage Container** binding.
* Optionally a **Bookshelf** (`enable_bookshelf`, off by default).

Discovery-managed resource groups can use independent regions via per-resource MRG location tags.

## How to deploy

The root module builds the full stack in one `terraform apply`: the platform,
Supercomputer, Workspace (+ chat model + project), and optionally a Bookshelf.
This is the supported path.

To link a new resource to infrastructure you already have, compose the
control-plane modules directly from your own configuration. They consume existing
resource IDs rather than creating platform prerequisites. See
[Reuse an existing resource](#reuse-an-existing-resource).

The Bookshelf is off by default (`enable_bookshelf = false`); see [The Bookshelf flag](#the-bookshelf-flag).

## Prerequisites

* Install Azure CLI 2.60+ and Terraform 1.9+.
* Use an Azure subscription where you can `az login`, with Owner or Contributor plus Role Based Access Control Administrator. Plain Contributor cannot create the module's role assignments.
* Register `Microsoft.Discovery` and its dependency resource providers using the Toolbox checks and remediation actions.
* Install [Discovery Toolbox](../discovery-toolbox/README.md#install) in VS Code for the readiness workflow below. Terraform itself can run without VS Code, but this utility does not provide a headless Azure-readiness gate.

### Prerequisite validation

Before applying, use Toolbox's Prerequisites, Permission Auditing, Quotas,
Region Readiness, and Network Security views. These cover resource-provider
registration, RBAC, approved regions, VM SKU availability, vCPU/GPU headroom,
Cosmos region availability, model TPM quotas, and the Discovery control-plane
service principal's NSP role prerequisites. Resolve blockers and investigate
inconclusive checks.

Toolbox settings are separate from Terraform inputs; the workflow does not
automatically read your Terraform configuration. Match the tenant, subscription,
resource group, control-plane region, workload SKU, and node counts. Check system
pool capacity as well as workload capacity. Review each resolved managed-resource
region separately, especially when overriding a resource's region:

| Infrastructure | Region to check |
| --- | --- |
| Supercomputer compute, VM SKUs, and cores quota | `supercomputer_managed_resource_group_location` |
| Workspace managed services, Cosmos, and model quotas | `workspace_managed_resource_group_location` |
| Optional Bookshelf managed services and model quotas | `bookshelf_managed_resource_group_location` |

Each unset override falls back to `managed_resource_group_location`, then
`location`. Include Bookshelf model requirements when enabling it; checking only
the configured chat model is insufficient. Toolbox SKU recommendations do not
change Terraform inputs: update your configuration explicitly and re-plan.

Use the prerequisite/readiness views, not Toolbox's Bicep deployment or
resource-creating validation stages, to prepare this Terraform deployment.
Toolbox validation is not an identical replacement for the removed shell
script's exit-code contract or sizing arithmetic. CI users must supply their own
live readiness gate. `terraform validate` and `terraform plan` remain necessary,
but neither proves that Azure quota, capacity, or permissions are sufficient.

## Configure

Set `resource_group_name`, `location`, and any explicit resource names in
`terraform.tfvars`. Names left unset derive from a shared random suffix.
Terraform validates `location` against `eastus`, `uksouth`, and `swedencentral`.
The utility excludes `eastus2` because new Discovery resource creation previously
failed there despite advertised support.

Resource-specific managed-resource-group overrides control the
`discovery.overridemrgregion` tags. Unlike `location`, those override inputs do
not have a Terraform region allowlist. Check service availability and network
placement requirements before changing them. The Workspace VNet and storage
remain in `location`; the Supercomputer VNet follows its managed-infrastructure
region.

The storage account disables shared keys. Grant the Terraform runner blob data
access as shown in the quickstart, and allow RBAC assignments time to propagate.

The root waits for the entire platform module before creating Discovery
resources, including role assignments, VNet peerings, and the storage private
endpoint/DNS configuration. The cluster identity receives Network Contributor
on both compute subnets and Managed Identity Operator on the kubelet identity.
Terraform ordering does not guarantee that Azure RBAC propagation has finished.
Standalone control-plane module callers must arrange equivalent prerequisites.

### Subscription network-security prerequisite

Follow [Configure network security for Microsoft Discovery](https://learn.microsoft.com/azure/microsoft-discovery/how-to-configure-network-security#assign-the-nsp-perimeter-joiner-role)
before applying. The documented Discovery control-plane service app has
application ID `92c174ac-8e41-4815-a1b7-d81b19ab03ce`. It needs Reader at
subscription scope and a custom role containing:

* `Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action`
* `Microsoft.Network/locations/networkSecurityPerimeterOperationStatuses/read`

The custom role's name does not need to be `Discovery NSP Perimeter Joiner`.
An existing differently named role is sufficient if its effective permissions,
assignable scopes, and assignment to that service principal cover the
subscription. Do not create duplicate roles merely to match a display name.
These subscription/tenant prerequisites remain outside this Terraform state.

### Clean redeployment after manual deletion

Use this procedure only when intentionally discarding the previous deployment
and all its data, not when migrating a live deployment to another region.

1. Stop other applies, portal creates, and cleanup operations. Back up the old
   state securely; it can contain sensitive values. For the default local
   backend, from this directory:

   ```powershell
   $archive = Join-Path $env:LOCALAPPDATA ("Discovery\TerraformBackups\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
   New-Item -ItemType Directory -Path $archive -ErrorAction Stop | Out-Null
   Copy-Item -LiteralPath .\terraform.tfstate -Destination $archive -ErrorAction Stop
   if (Test-Path -LiteralPath .\terraform.tfstate.backup) {
       Copy-Item -LiteralPath .\terraform.tfstate.backup -Destination $archive -ErrorAction Stop
   }
   ```

   If using another workspace or a remote backend, back up that workspace's
   actual state instead. Do not commit or share state or saved plan files.

2. Inventory each old customer resource group and confirm every resource is
   disposable. Delete service-owned resources through their Discovery APIs
   before deleting the customer group: workspaces before their linked
   supercomputers, and node-pool children before their supercomputer. Use
   `az resource delete --ids <discovery-resource-id> --api-version 2026-06-01`,
   without `--no-wait`, and stop if deletion fails. If a downstream AKS operation
   is still in progress, inspect it and allow it to finish rather than starting
   overlapping deletes. Escalate stuck service-managed operations to support.
   Let Discovery remove its MOBO broker and managed infrastructure; a direct
   broker delete can return `UnauthorizedMoboBrokerResourceModification` even
   for a subscription Owner. Do not bypass this protection or delete managed
   groups during parent provisioning/deletion. Once Discovery owners are gone,
   delete the exact customer groups with `az group delete`, without `--no-wait`.
   Check that both customer and managed groups have disappeared before
   proceeding. Orphaned managed groups may need separate cleanup after the
   parent is gone; investigate locks, deny assignments, or stuck operations
   rather than blindly forcing deletion.

3. Configure a new customer resource-group name and the desired region in
   `terraform.tfvars`. Create the new group outside Terraform and grant the
   signed-in Terraform runner blob data access. Match `$rg` and `$location` to
   the new configuration; use a group name not occupied by an earlier attempt:

   ```powershell
   $sub = az account show --query id -o tsv
   if ($LASTEXITCODE -ne 0) { throw "Cannot determine subscription" }
   $env:ARM_SUBSCRIPTION_ID = $sub
   $rg = "rg-discovery-terraform"
   $location = "uksouth"
   az group create --subscription $sub --name $rg --location $location
   if ($LASTEXITCODE -ne 0) { throw "Resource group creation failed" }
   $oid = az ad signed-in-user show --query id -o tsv
   if ($LASTEXITCODE -ne 0) { throw "Cannot determine runner object ID" }
   az role assignment create --subscription $sub --assignee-object-id $oid --assignee-principal-type User --role "Storage Blob Data Owner" --scope "/subscriptions/$sub/resourceGroups/$rg"
   if ($LASTEXITCODE -ne 0) { throw "Blob data role assignment failed" }
   ```

   Service-principal runners need their own principal ID/type instead.
   Confirm provider registration, operator role-assignment permissions, the
   subscription network-security prerequisite above, and regional readiness
   through Toolbox. The [provider registration utility](../resource-provider-registration/Register-DiscoveryResourceProviders.ps1)
   can register the complete documented dependency list with `-Wait`; do not
   check only `Microsoft.App` and `Microsoft.ContainerService`. Allow new role
   assignments to propagate. AzureRM v4 requires an explicit subscription ID;
   keep `ARM_SUBSCRIPTION_ID` set in the terminal used for plan/apply.

4. Use a new Terraform workspace with an empty state, preserving the old state
   for recovery. Do not select the old workspace and apply the new configuration
   against it, and do not reuse any old saved plan:

   ```powershell
   terraform init
   if ($LASTEXITCODE -ne 0) { throw "Terraform initialization failed" }
   terraform workspace new discovery-clean
   if ($LASTEXITCODE -ne 0) { throw "Fresh workspace creation failed; inspect existing workspaces" }
   terraform validate
   if ($LASTEXITCODE -ne 0) { throw "Terraform validation failed" }
   terraform plan '-out=deployment.tfplan' -no-color
   if ($LASTEXITCODE -ne 0) { throw "Terraform plan failed" }
   ```

   Review the plan: a clean deployment should create resources in the new
   group, not destroy resources from an earlier attempt. Only after reviewing
   it, run `terraform apply deployment.tfplan`. New workspaces do not migrate or
   clean up resources belonging to the old state.

   In PowerShell, quote the entire `-out=...` argument when the filename contains
   a dot; otherwise it can be split into multiple native-command arguments.
   An existing workspace can be selected with `terraform workspace select
   discovery-clean`; do not recreate it. If needed, the global `-chdir=...`
   option goes before the Terraform subcommand, not after the workspace name.

## Common issues

* Foundry capability-host creation can fail if `Microsoft.App` or `Microsoft.ContainerService` is unregistered. Complete dependency registration before retrying; registering a provider does not repair an already failed Foundry account.
* `RequestConflict` or `ResourceGroupBeingDeleted` means provisioning or cleanup is still in progress. Wait for a terminal state and inspect the correlation ID rather than starting overlapping operations.
* `ResourceGroupDeletionTimeout` with in-use subnets/NSGs and a MOBO broker error can mean the Discovery owner or its AKS node pool has not finished deletion. Check the underlying AKS operation, delete through the Discovery owner API, and retry group deletion only after service cleanup completes. Detaching NSGs does not release a subnet held by a VM scale set.
* If workspace creation reports `context deadline exceeded`, check whether Azure completed it server-side. If it is `Succeeded` but absent from Terraform state, import it and re-plan before retrying.
* For storage 403 errors, check blob data permissions and propagation. If accessing the private blob endpoint, also verify private network connectivity and DNS; RBAC alone does not grant network access.
* `PrincipalNotFoundError` can occur before a freshly created UAMI has replicated in Entra ID. Allow propagation and retry.
* Changing `location` forces storage-account replacement. Existing deployments need a blob data migration, not a straight apply.

## Architecture

A thin root ([main.tf](main.tf)) assembles reusable modules into one apply.
Each Discovery resource has one definition using the `2026-06-01` API.

### Module layout

```text
utilities/terraform/
├── main.tf                # end-to-end assembly (single apply)
└── modules/
    ├── platform/          # network, identities, storage, RBAC, storage container
    └── control-plane/     # thin wrappers over one Microsoft.Discovery/* resource each
        ├── supercomputer/ # + node pool children
        ├── workspace/     # + chat model deployment and project children
        ├── bookshelf/     # optional, retained behind enable_bookshelf
        └── tool/          # standalone Terraform-managed tool registration
```

The root creates the shared prerequisites (via `platform`) and wires them into
the Supercomputer, Workspace, and optional Bookshelf modules. The Tool module is
available for standalone compositions, but is not called by the root. Each
control-plane module owns one Discovery type and its children and never creates
platform resources. Every module requires an existing resource group.

## Reuse an existing resource

The root always builds the full stack; it has no "bring your own" flag. For an
advanced composition, call the control-plane modules with existing prerequisite
IDs. For example, the following creates a new Supercomputer using existing
subnets and identities. To link a new Workspace to an existing Supercomputer,
pass that Supercomputer's ID in the Workspace module's `supercomputer_ids`.
These modules create their named resources; they do not automatically adopt
existing resources into Terraform state.

```hcl
module "supercomputer" {
  source = "./modules/control-plane/supercomputer"

  name              = "sc-prod"
  location          = "uksouth"
  resource_group_id = "/subscriptions/.../resourceGroups/rg-mine"

  system_subnet_id      = "/subscriptions/.../subnets/aks"
  cluster_identity_id   = "/subscriptions/.../userAssignedIdentities/uami-cluster"
  kubelet_identity_id   = "/subscriptions/.../userAssignedIdentities/uami-kubelet"
  workload_identity_ids = ["/subscriptions/.../userAssignedIdentities/uami-workload"]

  node_pools = {
    gpu = {
      subnet_id      = "/subscriptions/.../subnets/nodepool"
      vm_size        = "Standard_NC4as_T4_v3"
      max_node_count = 3
    }
  }
}
```

See the [Supercomputer](modules/control-plane/supercomputer/README.md),
[Workspace](modules/control-plane/workspace/README.md), and
[Bookshelf](modules/control-plane/bookshelf/README.md) usage examples and their
adjacent variable declarations for the complete input contracts.

## The Bookshelf flag

The Discovery Bookshelf remains part of this utility and is off by default.
With `enable_bookshelf = false`, Terraform does not create one. Enable it
explicitly after the core stack is healthy:

```hcl
# terraform.tfvars
enable_bookshelf = true
```

| Variable | Default | Effect |
| --- | --- | --- |
| `enable_bookshelf` | `false` | Create a Bookshelf as part of the full-stack apply. |
| `bookshelf_public_network_access` | `"Disabled"` | Public network access on the created Bookshelf (`"Disabled"` or `"Enabled"`). |

Bookshelf provisioning can take about 40 minutes and fail independently of the
core stack. Keeping it off avoids that dependency on the initial deployment.
When enabled, a Bookshelf failure can still fail the overall apply; it does not
automatically roll back resources already created. Check its regional quota and
prerequisites in Toolbox before re-applying. The root's `bookshelf_id` output is
null when disabled and contains the resource ID when enabled.

## Tool and agent publishing

The [Terraform Tool module](modules/control-plane/tool/README.md) is retained
for Terraform-managed tool registration and lifecycle. Call it from your own
configuration with a tool definition, version, environment variables, and an
existing resource group. It registers `Microsoft.Discovery/tools` using API
version `2026-06-01` and exports the tool ID. Container image builds, registry
publication, and prerequisite role assignments remain outside the module.

Alternatively, use
[Discovery Toolbox's publishing capabilities](../discovery-toolbox/README.md#key-capabilities)
for the image and tool deployment workflow. Select the same tenant, subscription,
and resource group, then use the existing Discovery infrastructure:

* Build container images remotely with Azure Container Registry Tasks, without a local Docker installation.
* Push images to your Azure Container Registry and verify the published image.
* Deploy/register the Discovery Tool through ARM using the tool definition and image configuration.
* Publish agents separately through Agent Publishing, including catalog-based agents, for use in the deployed environment.

Registry access, build permissions, and tool-specific configuration still need
to be supplied. The Terraform root does not provision an ACR or publish images,
tools, or agents. Its outputs expose infrastructure IDs for downstream use;
Toolbox does not automatically consume Terraform outputs or take over its state.

> [!IMPORTANT]
> Toolbox-published tools and agents are not managed by this Terraform root.
> Do not manage the same resource concurrently through Terraform and Toolbox.
> Tools created by the standalone Terraform Tool module belong to the calling
> configuration's state. If switching between Terraform and Toolbox management,
> deliberately migrate ownership and state first. Removing a Terraform module
> call can plan deletion of the tool; this utility does not automate migration.

## Scope decisions

* The standalone preflight package was removed because it duplicated Toolbox's provider, region, quota, and network-security checks. Separate catalogs and a partial Terraform-input parser had drifted. Toolbox owns the operator readiness workflow; Terraform keeps its input validation and resource preconditions. There is no replacement headless gate bundled here.
* The network-isolation ADR was removed because it described an older implementation and referenced obsolete files. The supported input combinations are enforced in the Workspace module and summarized below, rather than maintained in a separate historical document.
* The standalone Tool module is retained so callers can manage Discovery Tool registration and lifecycle in Terraform state. It is separate from the full-stack root and does not build or push container images. Toolbox provides an alternative build, push, verification, and ARM deployment workflow, not a replacement for Terraform state ownership.

Bookshelf is retained because it is an active, documented root feature. The
platform, Supercomputer, and Workspace modules, their input/output contracts,
provider requirements, root lockfile, and Terraform ignore rules remain in place.

### Network isolation

The root defaults `network_isolation` to `true` and passes the agent,
private-endpoint, and workspace subnet IDs. When it is `false`, the root passes
null for those IDs and the Workspace module omits them from the API payload.
The module precondition rejects inconsistent combinations. Passing subnet IDs
with isolation disabled previously left the managed backend unable to reach
Cosmos, breaking project creation and deletion.

The platform still creates its VNets, subnets, and private storage endpoint
regardless of this flag. Disabling workspace isolation is not a switch to a
fully public deployment. Standalone Workspace module callers must set isolation
explicitly when supplying subnets; that module defaults to `false`, unlike the
end-to-end root.

## Notes

* Resource names derive from a shared random suffix unless overridden. The node pool name defaults to `nodepool1`.
* Discovery tags merge from common tags to resource-specific tags, then computed managed-resource-group tags and required module tags where applicable. Computed and required values win.
* The root wires one full-stack path. Advanced reuse requires a standalone composition, not a root feature flag.
* State uses a local backend by default. Configure an appropriate remote backend before sharing deployments, and retain the committed provider lockfile for reproducible initialization.

## Local validation

```powershell
terraform init -backend=false -lockfile=readonly
terraform fmt -check -recursive
terraform validate
terraform test
```

The focused tests use mocked providers and plan-only runs. They check regional
configuration and AKS role assignments without creating Azure resources or
modifying deployment state. They do not prove live quota, capacity, permissions,
or RBAC propagation.

## Deployment lifecycle evidence and open validation

This branch captures local changes developed from commit
`fa9047884ddaa6bfd9dda2a49cbf39aa7bc08f5b` of the Terraform contribution in
[microsoft/discovery#103](https://github.com/microsoft/discovery/pull/103).
An earlier trial used uncommitted changes. The results below instead describe
the fully logged October 15, 2026 rerun of exact commit
`3ae7166db1d7b9691308adab1f2b7a593c5cd8c8`, including its optional user-access
implementation and four mocked tests. All 34 archived candidate files were
verified byte-for-byte unchanged after teardown. Subsequent documentation
updates are not part of that live-applied commit.

### Live-tested configuration

The October 15 run used Terraform 1.16.5, AzureRM 4.81.0, AzAPI 2.11.0, and
random 3.9.0 with Discovery API version `2026-06-01`. Control-plane resources,
workspace-managed infrastructure, and supercomputer-managed infrastructure were
all in UK South. Bookshelf was disabled. The following sanitized inputs capture
the relevant placement and workload-pool choices, not the complete private
configuration:

```hcl
resource_group_name                          = "rg-discovery-terraform"
location                                     = "uksouth"
supercomputer_managed_resource_group_location = "uksouth"
workspace_managed_resource_group_location     = "uksouth"
bookshelf_managed_resource_group_location     = "uksouth"
enable_bookshelf                             = false
node_pool_vm_size                            = "Standard_D4s_v6"
node_pool_min_node_count                     = 0
```

Create the customer group and complete prerequisites before applying, as in the
quickstart. This example is not a capacity or product-support guarantee.

| Area | Observed result | Limitation |
| --- | --- | --- |
| Provisioning | Apply succeeded: 37 added, zero changed, zero destroyed, in about 74 minutes. | One environment and configuration; not a capacity or general reliability guarantee. |
| Drift | A normal post-apply `plan -detailed-exitcode` returned zero: no changes. | Captured before the separately approved smoke-test tool and extra user grant; not a claim that no out-of-state resources existed later. |
| Workspace access | The optional Terraform-managed workspace user grant was verified; the user reported that the UI appeared to work without a manual workspace-access fix. | Basic UI smoke only, not full workflow or compute-user access validation. |
| Workload execution | One 1-CPU, 512-MiB, single-replica job with no data mounts succeeded in about 129 seconds on `Standard_D4s_v6`, with verified arithmetic output and success marker. AKS snapshots showed workload nodes scale from zero to one and later back to zero. | Submission required a separate temporary test-RG Discovery Platform Contributor grant after an initial 403. No GPU or scientific workflow was tested; official SKU support remains unconfirmed. |
| Regions | The tested deployment was same-region UK South. | Cross-region deployment and Bookshelf were not validated by this run. |
| Teardown | Final state had zero resources; all four managed groups, the customer group, temporary tool, and both temporary group-scoped user grants were confirmed removed. | This was not a single-pass full destroy; workspace deletion needed a fresh-plan retry, and service-side RBAC cleanup needed to be accounted for. |

### Identity mapping and workload SKU questions

The snapshot grants **Managed Identity Operator to the cluster identity, scoped
to the kubelet identity resource**. It does not grant that role to the kubelet
identity on the cluster identity. This follows the
[AKS pre-created kubelet identity guidance](https://learn.microsoft.com/azure/aks/managed-identity-overview#pre-created-kubelet-managed-identity).
Discovery-specific guidance reported during review describes the reverse
mapping; that discrepancy remains to be reconciled with the product owners.
Successful provisioning, one CPU smoke job, and mocked assertions do not establish that every
permission is necessary or sufficient. No reverse or additional grant has been
added to resolve the discrepancy speculatively.

`Standard_D4s_v6` is retained in the workload-pool allowlists to preserve the
configuration accepted in this run. It is outside the published workload VM
size enumeration in the
[2026-06-01 node-pool reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/2026-06-01/supercomputers/nodepools).
Official workload-pool support remains unconfirmed. The successful CPU smoke
demonstrates one small workload on this configuration, not product support or
certification for other workloads.

The job's top-level status and operation history reported Succeeded, with a
completion timestamp and verified output, while nested `result.status` remained
TaskAccepted and `percentageComplete` remained zero. This API progress
inconsistency is recorded separately from the successful execution.

### Observed staged teardown

The run used reviewed, saved destroy plans for these stages, checking Azure
cleanup between stages:

1. Delete the workspace-scoped user grant, workspace children, and workspace.
   The reviewed targets included both `module.workspace` and the root
   `azurerm_role_assignment.workspace_contributor` resource. The first parent
   delete returned HTTP 409 `CannotDeleteResource`, identifying chat-model and
   project children. Terraform had removed the children from state. After Azure child listings
   were verified empty, a fresh workspace-only destroy plan completed deletion.
   The workspace-managed group and its nested Container Apps group disappeared.
2. Delete the workload pool through Terraform/Discovery. Its removal was
   verified in Terraform state, Discovery, AKS, and the backing VM scale set.
3. Delete the supercomputer. The Discovery resource and both associated
   managed groups were verified absent before removing the platform.
4. Destroy the remaining platform resources. The reviewed plan contained 28
   delete actions and completed with empty Terraform state.
5. Inspect remaining customer-group resources. Six service-created network
   security groups were verified unattached; these and the temporary smoke
   tool remained outside Terraform. The customer group was deleted last, and
   its absence and removal of both temporary user grants were verified.

Azure activity tied three Terraform-managed role-assignment deletions to
Discovery cleanup: the cluster's workload-subnet Network Contributor grant
during pool deletion, then its system-subnet Network Contributor and
cluster-to-kubelet Managed Identity Operator grants during supercomputer
deletion. Subsequent refreshes accounted for these already-absent resources.
The run therefore had 34 explicit Terraform destroys plus three service-side
role removals, accounting for all 37 originally created managed instances.
The counts include two local random-string resources, not just Azure resources.

These are observations and recovery checkpoints, not an automatic teardown
implementation. Do not reuse historical plans. Targeted destroy is an
exceptional recovery technique: review each fresh plan, stop on errors, and
verify the full remaining state afterward. Do not apply the normal configuration
between teardown stages, because it can recreate resources already removed.
Preserve remaining identities, permissions, networking, and storage until their service
owners finish cleanup.

Earlier, separate manual deployments had stuck cleanup involving missing
identities and failed managed-service operations. Those incidents were not
caused by this Terraform contribution, but motivate the owner-first precautions.
Exact command arguments, UTC timings, exit codes, stdout/stderr, source archive,
plans, state snapshots, failures, and recovery attempts are retained privately.
Raw diagnostics can contain sensitive configuration and identity metadata; do
not attach them to public issues or PRs without sanitization. No support incident
details, raw state, binary plans, or personal configuration are included here.

### Remaining acceptance checks

Before claiming broader validation:

* Reconcile Discovery-specific identity guidance with the tested
  cluster-to-kubelet Managed Identity Operator mapping.
* Confirm an officially supported workload SKU and validate a representative
  scientific workload, including its storage and data-access requirements.
* Agree the intended compute-user role scope; the opt-in workspace-only grant
  must not be presented as complete Scientist-persona access.
* Validate any changed integration candidate separately from this tested commit.
  Mocked tests do not exercise Azure deletion races or prove prerequisite
  propagation.

Before the logged apply, pinned-provider initialization,
`terraform fmt -check -recursive`, `terraform validate -no-color`, and
`terraform test -no-color` passed (four mocked runs, zero failed). Terraform
commands used the isolated archived utility via `-chdir`; the developer's
original state and plans were not used for this run.

## References

* [Deploy Microsoft Discovery infrastructure using Bicep](https://learn.microsoft.com/azure/microsoft-discovery/quickstart-infrastructure-bicep?tabs=CLI)
* [Microsoft.Discovery Supercomputers template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/supercomputers)
* [Microsoft.Discovery Workspaces template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/workspaces)
* [Microsoft.Discovery Bookshelves template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/bookshelves)
* [Terraform Tool module](modules/control-plane/tool/README.md)
* [Discovery Toolbox](../discovery-toolbox/README.md)
* [Terraform module composition](https://developer.hashicorp.com/terraform/language/modules/develop/composition)
* [Azure resource naming guidance](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming)
