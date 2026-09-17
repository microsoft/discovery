---
title: Bicep utility for Microsoft Discovery
description: Single-template Bicep deployment for a Microsoft Discovery workspace, supercomputer, project, chat model, storage, network, and least-privilege role assignments.
ms.topic: how-to
---

# Bicep utility (**DRAFT — WIP**)

> **Status:** Draft. Under active development and testing. Interfaces, defaults, and role scopes may change before this is promoted to a supported utility. Do **not** use in production yet.

Single-file Bicep template that deploys a working Microsoft Discovery footprint with **least-privilege** role assignments per identity slot, rather than the coarse-grained "Owner on the resource group" pattern used in most quickstarts.

For a supported, production-ready deployment path today, use the Terraform utility in [`utilities/terraform/`](../terraform/README.md).

## What this deploys

A single resource group containing:

* Microsoft Discovery Supercomputer + Node Pool
* Microsoft Discovery Workspace + Project
* Chat Model Deployment
* Discovery Storage Container backed by a dedicated Storage Account
* Virtual Network + AKS subnet
* User-assigned managed identities (workspace, cluster, kubelet)
* Azure Container Registry with RBAC-only auth

## Least-privilege role model

Every identity slot receives only the specific role it needs, scoped as narrowly as possible:

| Identity | Role | Scope |
| --- | --- | --- |
| Workspace identity | Discovery Platform Contributor | Resource group |
| Workspace identity | Storage Blob Data Contributor | Storage account |
| Cluster identity | Network Contributor | **AKS subnet only** (not the VNet) |
| Cluster identity | Managed Identity Operator | Kubelet identity |
| Kubelet identity | AcrPull | Container registry |

Reference: [Discovery advanced RBAC — granular role assignments per identity](https://learn.microsoft.com/azure/microsoft-discovery/) (link to be finalized).

## Quick check

Build the template locally to validate:

```bash
az bicep build --file discovery.bicep --stdout > /dev/null
```

Zero warnings, zero errors expected.

## Known gaps (tracked here until the utility exits draft)

* No preflight script (see the Terraform utility's [`preflight.sh`](../terraform/preflight.sh) for the parity target).
* No teardown script.
* Not wired into any published quickstart.
* End-to-end deployment has been exercised in `uksouth`; other approved regions are still pending.

## Feedback

This template is being iterated on. Open an issue or comment on the tracking PR before relying on any specific role/scope combination.
