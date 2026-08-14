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

This utility is a minimal, end-to-end Terraform module for a Microsoft Discovery services environment. It uses the AzureRM provider for platform primitives (VNet, UAMI, storage, role assignments) and the AzAPI provider, pinned to API version `2026-06-01`, for every `Microsoft.Discovery/*` resource.

The provider split is deliberate: `Microsoft.Discovery/*` is not yet in the AzureRM provider's resource catalog, so AzAPI is required for those types. Every other resource uses AzureRM to benefit from strongly-typed schemas, better plan output, and stable state migrations.

## Quickstart (TL;DR)

For an experienced Azure/Terraform user with an active `az login`, the full happy path is:

```bash
# 1. create the RG (kept out of Terraform state on purpose)
az group create --name rg-discovery-terraform --location uksouth

# 2. grant yourself blob data access on the RG (needed because the storage account disables shared keys)
MY_OID=$(az ad signed-in-user show --query id -o tsv)
SUB_ID=$(az account show --query id -o tsv)
az role assignment create --assignee "$MY_OID" \
  --role "Storage Blob Data Owner" \
  --scope "/subscriptions/$SUB_ID/resourceGroups/rg-discovery-terraform"

# 3. clone / cd into this directory, then preflight
cd utilities/terraform
cp -n terraform.tfvars.example terraform.tfvars   # set deployment-specific values
./preflight.sh                                    # 9 checks; exits non-zero on any FAIL

# 4. init / plan / apply
terraform init
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

## Two ways to deploy

The same root module supports both approaches — see [Deployment modes](#deployment-modes) for details:

* **Full stack (default)** — one `terraform apply` builds the platform, Supercomputer, Workspace (+ chat model + project), and optionally a Bookshelf.
* **Bring your own (BYO)** — pass an existing `existing_supercomputer_id`, `existing_workspace_id`, or `existing_bookshelf_id` and the root reuses that resource and creates the rest around it. Mixable in a single apply.

The Bookshelf is off by default (`enable_bookshelf = false`); see [The Bookshelf flag](#the-bookshelf-flag).

## Prerequisites

* Azure CLI 2.60+ and Terraform 1.9+.
* An Azure subscription where you can `az login`, with **Owner** (or **Contributor** + **Role Based Access Control Administrator**) — plain Contributor fails on the module's role assignments.
* The `Microsoft.Discovery`, `Microsoft.Network`, `Microsoft.ManagedIdentity`, `Microsoft.Storage`, `Microsoft.Authorization`, and `Microsoft.App` providers registered (`preflight.sh` checks all 25).

## Configure

Set `resource_group_name`, `location`, and any explicit resource names in `terraform.tfvars` (copy `terraform.tfvars.example`). Names left unset derive from a shared random suffix. `location` must be `eastus`, `uksouth` (recommended), or `swedencentral` — the validation and preflight reject regions the Discovery RP advertises but silently fails creates in (e.g. `eastus2`).

Before applying, run `./preflight.sh`. It runs deterministic checks — RP registration (Discovery + 24 dependencies), region gates, AKS/node-pool SKU availability, compute-cores quota, Cosmos region, and chat-model TPM quota — and exits non-zero on any hard failure that Azure would otherwise surface hours into an apply.

The first apply also needs the identity running Terraform to hold **Storage Blob Data Owner** (or Contributor) on the RG, because the storage account disables shared keys (step 2 of the Quickstart). Wall time is ~20–45 minutes, dominated by the supercomputer and workspace.

## Common issues

* **Workspace `context deadline exceeded`** — the workspace is usually provisioned server-side by the time Terraform gives up. Confirm it shows `Succeeded`, `terraform import` it, then re-plan; the run picks up where it left off.
* **Storage 403 on apply** — the blob data role hasn't propagated. Wait ~60 s and re-run.
* **`PrincipalNotFoundError` on first apply** — Entra ID replication race for a freshly-created UAMI. Re-run apply; no code change needed.

## Architecture

A thin root ([main.tf](main.tf)) assembles reusable modules into one apply; BYO scenarios pass an existing resource ID and the root wires the rest around it. One definition per resource, all on the `2026-06-01` API.

### Module layout

```text
utilities/terraform/
├── main.tf                # end-to-end assembly (single apply)
└── modules/
    ├── platform/          # network, identities, storage, RBAC, storage container
    └── control-plane/     # thin wrappers over one Microsoft.Discovery/* resource each
        ├── supercomputer/ # + node pool children
        ├── workspace/     # + chat model deployment and project children
        ├── bookshelf/
        └── tool/
```

The root creates the shared prerequisites (via `platform`) and wires them into the control-plane modules; each control-plane module owns exactly one Discovery type and its children and never creates platform resources. Every module requires an existing resource group.

## Deployment modes

Both modes run through the same root ([main.tf](main.tf)); the only difference is
whether you hand it an existing resource ID.

**1. Full stack (default).** `terraform apply` creates the platform,
Supercomputer, Workspace (+ chat model + project), and optional Bookshelf in one
apply. Terraform orders the modules automatically.

**2. Reuse existing resources (BYO).** Supply a resource's ID and the root skips
its module, wiring your resource into the rest. Each control-plane resource has
its own knob:

| Variable | Effect when set |
| --- | --- |
| `existing_supercomputer_id` | Skip the Supercomputer module **and its network** (VNet, AKS/node-pool subnets, peering); link the Workspace to your Supercomputer. |
| `existing_workspace_id` | Skip the Workspace module and its chat model deployments and projects. |
| `existing_bookshelf_id` | Skip the Bookshelf module. |

```hcl
# terraform.tfvars -- reuse a supercomputer, create everything else
existing_supercomputer_id = "/subscriptions/.../Microsoft.Discovery/supercomputers/sc-prod"
```

Anything you don't pass is created normally, so you can mix created and existing
resources in a single apply.

**Advanced: call a module standalone.** Because the control-plane modules only
consume IDs (they never create platform resources), you can also call one
directly from your own configuration:

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

Each module's inputs are documented in its own `README.md`.

## The Bookshelf flag

The Discovery Bookshelf is **off by default** — a plain `terraform apply` never
creates one. Enable it explicitly:

```hcl
# terraform.tfvars
enable_bookshelf = true
```

| Variable | Default | Effect |
| --- | --- | --- |
| `enable_bookshelf` | `false` | Create a Bookshelf as part of the full-stack apply. |
| `existing_bookshelf_id` | `null` | BYO: reuse an existing Bookshelf and skip creating one (takes precedence over `enable_bookshelf`). |
| `bookshelf_public_network_access` | `"Disabled"` | Public network access on the created Bookshelf (`"Disabled"` or `"Enabled"`). |

It is gated off because the Bookshelf is heavy (~40 minutes) and its backend
provisioning can fail independently of your configuration; keeping it opt-in
means a failed Bookshelf never blocks the core stack. Turn it on only once the
rest of the stack is up and healthy, then re-apply.

## Notes

* **Names** derive from a shared random suffix (`sc-`, `ws-`, `prj-`, `stc-`, `stg`, `vnet-`, `uami-<purpose>-`, node pool `nodepool1`); set explicit names in `terraform.tfvars` to override, subject to Azure's per-resource constraints.
* **Tags** merge as `common_tags` → `resource_tags` → required Discovery tags (required win). `discovery.overridemrgregion` is constrained to the `location` allowlist (`eastus`, `uksouth`, `swedencentral`).
* **Network isolation** defaults to `true` and always provisions the private topology — see [ADR 0001](docs/adr/0001-network-isolation-posture.md).

## References

* [Deploy Microsoft Discovery infrastructure using Bicep](https://learn.microsoft.com/azure/microsoft-discovery/quickstart-infrastructure-bicep?tabs=CLI)
* [Microsoft.Discovery Supercomputers template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/supercomputers)
* [Microsoft.Discovery Workspaces template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/workspaces)
* [Microsoft.Discovery Bookshelves template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/bookshelves)
* [Microsoft.Discovery Tools template reference](https://learn.microsoft.com/azure/templates/microsoft.discovery/tools)
* [Terraform module composition](https://developer.hashicorp.com/terraform/language/modules/develop/composition)
* [Azure resource naming guidance](https://learn.microsoft.com/azure/cloud-adoption-framework/ready/azure-best-practices/resource-naming)
