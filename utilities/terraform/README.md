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
The example uses `rg-discovery-terraform`, control-plane region `uksouth`, and
Supercomputer managed-infrastructure region `swedencentral`. Match the resource
group command below to your configuration before running it.

```bash
# 1. create the RG (kept out of Terraform state on purpose)
az group create --name rg-discovery-terraform --location uksouth

# 2. grant yourself blob data access on the RG (needed because the storage account disables shared keys)
MY_OID=$(az ad signed-in-user show --query id -o tsv)
SUB_ID=$(az account show --query id -o tsv)
az role assignment create --assignee "$MY_OID" \
  --role "Storage Blob Data Owner" \
  --scope "/subscriptions/$SUB_ID/resourceGroups/rg-discovery-terraform"

# 3. init / validate / plan / apply
terraform init
terraform validate
terraform plan  -out=tfplan
terraform apply tfplan
```

Wall time is ~20-45 minutes, dominated by the supercomputer + workspace creates.

## What you build

One resource group containing:

* Two peered VNets (workspace + supercomputer) with six subnets, four user-assigned identities with seven least-privilege role assignments, and a storage account with a blob private endpoint.
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
Cosmos region availability, model TPM quotas, and the AIFSPInfrastructure/NSP
role prerequisites. Resolve blockers and investigate inconclusive checks.

Toolbox settings are separate from Terraform inputs; the workflow does not
automatically read your Terraform configuration. Match the tenant, subscription,
resource group, control-plane region, workload SKU, and node counts. Check system
pool capacity as well as workload capacity. Review each resolved managed-resource
region separately, especially when using the split-region example:

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

## Common issues

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

## References

* [Deploy Microsoft Discovery infrastructure using Bicep](https://learn.microsoft.com/azure/microsoft-discovery/quickstart-infrastructure-bicep?tabs=CLI)
* [Microsoft.Discovery Supercomputers template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/supercomputers)
* [Microsoft.Discovery Workspaces template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/workspaces)
* [Microsoft.Discovery Bookshelves template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/bookshelves)
* [Terraform Tool module](modules/control-plane/tool/README.md)
* [Discovery Toolbox](../discovery-toolbox/README.md)
* [Terraform module composition](https://developer.hashicorp.com/terraform/language/modules/develop/composition)
* [Azure resource naming guidance](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming)
