---
title: Bicep utility for Microsoft Discovery
description: Single-template Bicep deployment for a Microsoft Discovery workspace, supercomputer, project, chat model, storage, network, and least-privilege role assignments.
ms.topic: how-to
---

# Bicep utility (**DRAFT — WIP**)

> **Status:** Draft. Under active development and testing. Interfaces, defaults, and role scopes may change before this is promoted to a supported utility. Do **not** use in production yet.

[uami.bicep](uami.bicep) deploys a Microsoft Discovery footprint with separate user-assigned managed identities and **least-privilege** role assignments per identity slot. For the maintained upstream quickstart, see [Microsoft Discovery documentation](https://learn.microsoft.com/azure/microsoft-discovery/).

For a supported, production-ready deployment path today, use the Terraform utility in [`utilities/terraform/`](../terraform/README.md).

## What this deploys

A single resource group containing:

* Microsoft Discovery Supercomputer + Node Pool
* Microsoft Discovery Workspace + Project
* Chat Model Deployment
* Discovery Storage Container backed by a dedicated Storage Account
* Virtual Network with AKS, node pool, workspace, private endpoint, agent, and search subnets
* User-assigned managed identities (workspace, cluster, kubelet, workload)

## Least-privilege role model

Every identity slot receives only the specific role it needs, scoped as narrowly as possible:

| Identity | Role | Scope |
| --- | --- | --- |
| Workspace identity | Discovery Platform Contributor | Resource group |
| Workspace identity | Storage Blob Data Contributor | Storage account |
| Cluster identity | Network Contributor | **AKS subnet only** (not the VNet) |
| Cluster identity | Managed Identity Operator | Kubelet identity |
| Kubelet identity | AcrPull | Resource group (no registry is created) |
| Kubelet identity | Storage Blob Data Contributor | Storage account |
| Workload identity | Storage Blob Data Contributor | Storage account |

References: [AKS pre-created kubelet managed identity](https://learn.microsoft.com/azure/aks/managed-identity-overview#pre-created-kubelet-managed-identity) and [Discovery granular role assignments](https://learn.microsoft.com/azure/microsoft-discovery/concept-managed-identities#advanced-configuration-granular-role-assignments-per-identity).

## Workspace networking

In [uami.bicep](uami.bicep), `networkIsolation` defaults to `true`; `false` selects public preview access. Both values retain all three workspace subnet IDs.

## Quick check

Build the template locally to validate:

```bash
az bicep build --file uami.bicep --stdout > /dev/null
```

The build should complete without errors. BCP081 warnings can occur when the installed Bicep compiler lacks type definitions for the Discovery API; those resource properties require service-side validation.

## Known gaps (tracked here until the utility exits draft)

* No preflight script (see the Terraform utility's [`preflight.sh`](../terraform/preflight.sh) for the parity target).
* No teardown script.
* Not wired into any published quickstart.
* End-to-end deployment has been exercised in `uksouth`; other approved regions are still pending.

## Feedback

This template is being iterated on. Open an issue or comment on the tracking PR before relying on any specific role/scope combination.
