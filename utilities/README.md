# Discovery Services Utilities

> **Scope:** these PowerShell utilities target **Microsoft Discovery services** (the Azure cloud experience). They are **not used by, and have no effect on, the local Microsoft Discovery app**. If you are evaluating the app on your laptop, you can safely skip this folder.

This directory contains standalone helper scripts for operators standing up or maintaining a Microsoft Discovery **services** deployment in Azure. Each utility is self-contained — its own README documents prerequisites, parameters, and operational notes.

## Inventory

| Utility | What it does | When to run |
|---|---|---|
| [`resource-provider-registration/`](resource-provider-registration/) | Registers every Azure resource provider Microsoft Discovery (and its dependencies) needs in a target subscription. Cross-platform PowerShell, auto-installs `Az.Accounts` / `Az.Resources`. | **First step when onboarding a new subscription** to Discovery services. |
| [`rbac-roles-assignment/`](rbac-roles-assignment/) | Assigns the complete set of Azure RBAC roles required for a Discovery persona (Platform Administrator or Scientist) to one or more users. Validates the executor's permissions, supports batch assignment, handles guest users. | After resource-provider registration, when granting users access to a Discovery services environment. |
| [`dataasset-migration/`](dataasset-migration/) | Migrates a Discovery v1 `DataContainer` + child `DataAssets` to the v2 `StorageContainer` + `StorageAssets` shape (API `2025-07-01-preview` → `2026-02-01-preview`). Control-plane metadata only — does **not** move blobs. | One-time migration for tenants that onboarded before the v2 storage model. |
| [`Supercomputer CLI/`](supercomputer-cli/) | Toolkit provides basic access to the Discovery Supercomputer API for submitting and running jobs directly on Supercomputer | Submit jobs directly to the supercomputer |
| [`delete-discovery-deployment/`](delete-discovery-deployment/) | Deletes all `Microsoft.Discovery` and supporting Azure resources in a resource group using the `2026-06-01` GA API, in strict dependency order, then removes the empty resource group. Bash script (`az` CLI / `jq` / `curl`), not PowerShell. | Tearing down a Discovery services deployment. **Destructive — deletes resources.** |

## Common prerequisites

| Requirement | Details |
|---|---|
| **PowerShell** | 5.1+ on Windows, 7.x on macOS / Linux. All three utilities are cross-platform. |
| **Az PowerShell modules** | `Az.Accounts >= 3.0.0`, `Az.Resources >= 7.0.0`. Each script auto-installs them unless `-SkipModuleInstall` is passed. |
| **Azure sign-in** | Each script invokes `Connect-AzAccount` if no session exists. |
| **Azure permissions** | Vary per utility — see each tool's README for the exact role required (typically Owner / User Access Administrator for RBAC; Contributor / Owner for provider registration). |

## Deleting a Discovery deployment

[`delete-discovery-deployment/delete-all-resources-2026-06-01.sh`](delete-discovery-deployment/delete-all-resources-2026-06-01.sh) tears down an entire Discovery services deployment. It deletes every `Microsoft.Discovery` and supporting Azure resource in a resource group — in strict dependency order (data assets → projects → agents → workspaces → supercomputers → storage → networking) — then deletes the now-empty resource group.

> ⚠️ **This is destructive and irreversible.** It permanently deletes resources and the resource group. Always run with `--dry-run` first to review the deletion plan.

Unlike the other utilities in this folder, this is a **Bash** script rather than PowerShell.

### Prerequisites

| Requirement | Details |
|---|---|
| **Shell** | Bash on Linux (including WSL) or Git Bash on Windows. |
| **Tooling** | `az` CLI (already signed in via `az login`), `jq`, and `curl` on `PATH`. |
| **Azure permissions** | Delete rights over the target resource group (typically Owner / Contributor). |

### Usage

```bash
./delete-all-resources-2026-06-01.sh \
    -s <subscription-id> -g <resource-group-name> \
    [--dry-run] [--verbose] [--force] [--continue-on-error]
```

**Required arguments**

| Flag | Description |
|---|---|
| `-s <id>` | Azure subscription ID. |
| `-g <name>` | Resource group name to tear down. |

**Options**

| Flag | Description |
|---|---|
| `--dry-run` | Print the deletion plan without deleting anything. Run this first. |
| `--verbose` | Print REST calls and responses (Bearer tokens redacted). |
| `--force` | Skip the interactive confirmation prompt. |
| `--continue-on-error` | Collect failures and continue instead of stopping (default behavior). |
| `-h`, `--help` | Show help and exit. |

### Examples

```bash
# 1. Preview what would be deleted (safe, no changes)
./delete-all-resources-2026-06-01.sh -s 00000000-0000-0000-0000-000000000000 -g my-discovery-rg --dry-run

# 2. Delete the deployment, skipping the confirmation prompt
./delete-all-resources-2026-06-01.sh -s 00000000-0000-0000-0000-000000000000 -g my-discovery-rg --force
```

> **Note:** The script uses a strict GA-only delete path (`2026-06-01`). If a `Microsoft.Discovery` resource fails to delete on that API version, the script stops. Network Security Groups are not deleted individually — they are removed when the resource group is deleted.

## What these utilities are **not**

- They are not part of the Discovery catalog (agents / starter kits / Copilot skills) — they are operator tooling.
- They are **not** invoked by any GitHub Actions workflow in this repository. They run locally against your Azure subscription.
- They are **not** required to install or use the Microsoft Discovery app (Windows desktop client). The app is fully self-contained.

## Support and contributions

For issues, improvements, or new utility proposals, open a [Discussion](https://github.com/microsoft/discovery/discussions) with the **services** surface tag, or submit a PR per [`CONTRIBUTING.md`](../CONTRIBUTING.md). Utility changes are CODEOWNERS-gated like the rest of the repo.
