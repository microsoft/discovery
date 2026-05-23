# Set-DiscoveryRoleAssignments.ps1

PowerShell script that assigns the complete set of Azure RBAC roles required for a **Microsoft Discovery** persona (Platform Administrator or Scientist) to one or more users.

The script is cross-platform (Windows / macOS / Linux), validates the executor's permissions before acting, supports batch assignment, handles guest users, and prints a clear three-section summary (Assigned / Failed / Skipped).

---

## Prerequisites

| Requirement | Details |
|---|---|
| PowerShell | 5.1+ on Windows, 7.x on macOS/Linux |
| Az modules | `Az.Accounts >= 3.0.0`, `Az.Resources >= 7.0.0` (auto-installed unless `-SkipModuleInstall`) |
| Executor role | **Owner**, **User Access Administrator**, or **Role Based Access Control Administrator** at the target scope |
| Sign-in | The script handles sign-in automatically (see [Authentication](#authentication)) |
| Target users | Must already exist in the tenant (guest users must be invited first) |

> The Microsoft Discovery Platform Administrator (Preview) role alone is **not** sufficient for the executor — that role cannot grant the Azure built-in roles (Storage, Network, Managed Identity, Azure AI, etc.) that each persona requires.

---

## Personas and roles

### Platform Administrator

Sets up and manages the Discovery platform.

| Role | Scope |
|---|---|
| Microsoft Discovery Platform Administrator (Preview) | Subscription or RG |
| Managed Identity Contributor | Subscription or RG |
| Managed Identity Operator | Subscription or RG |
| Storage Account Contributor | Subscription or RG |
| Storage Blob Data Contributor | Subscription or RG |
| Network Contributor | Subscription or RG |
| AcrPush | Subscription or RG |
| Reader | **Always Subscription** |
| Azure AI Owner | Subscription, or Workspace Managed RG (when Scope=ResourceGroup) |
| Microsoft Discovery Bookshelf Index Data Reader - Preview | Subscription or RG |

### Scientist

Performs research using Discovery workflows.

| Role | Scope |
|---|---|
| Microsoft Discovery Platform Contributor (Preview) | Subscription or RG |
| Storage Account Contributor | Subscription or RG |
| Storage Blob Data Contributor | Subscription or RG |
| AcrPush | Subscription or RG |
| Reader | **Always Subscription** |
| Azure AI User | Subscription, or Workspace Managed RG (when Scope=ResourceGroup) |
| Microsoft Discovery Bookshelf Index Data Reader - Preview | Subscription or RG |

---

## ⚠ Important: Resource Group scope assumption

When you choose **`-Scope ResourceGroup`**, the script grants every non-subscription role at that single resource group. **This works only if every Azure resource that Microsoft Discovery uses lives in that same resource group**, including (but not limited to):

- Microsoft Discovery workspace
- Azure Container Registry (ACR)
- Storage account(s) used by Discovery
- Virtual Network / Subnets used by Discovery
- User-Assigned Managed Identities used by Discovery
- Any other dependent resources referenced by the workspace

If your Discovery resources are spread across multiple resource groups (for example, ACR or VNET in a shared/networking RG), **RG-scoped assignments will not cover them** and the platform will hit "missing permission" errors at runtime. In that case use `-Scope Subscription` instead, or run the script multiple times — once per resource group — using the appropriate persona.

The two roles that always behave specially regardless of `-Scope`:

- **Reader** is always assigned at **Subscription** scope (it must cover all Discovery dependencies).
- **Azure AI Owner** (Platform Administrator) and **Azure AI User** (Scientist) are assigned at the **Workspace Managed Resource Group** when `-Scope ResourceGroup`, and at **Subscription** when `-Scope Subscription`.

---

## Parameters

| Parameter | Required | Description |
|---|---|---|
| `-Persona` | Interactive if omitted | `PlatformAdministrator` (or `1`), `Scientist` (or `2`) |
| `-SubscriptionId` | Yes | Azure subscription GUID where Discovery is deployed |
| `-TenantId` | Optional | Azure AD tenant GUID. Use when the subscription belongs to a different tenant than the one you are currently signed in to. If omitted, the script prompts interactively |
| `-UserIds` | Yes | One or more UPNs or Object IDs. Separate with `,`, `;`, or pass an array |
| `-Scope` | Interactive if omitted | `Subscription` or `ResourceGroup` (default: `ResourceGroup`) |
| `-ResourceGroupName` | When `-Scope ResourceGroup` | Resource group hosting Discovery |
| `-WorkspaceManagedRGName` | Optional (RG scope only) | Managed RG of the Discovery workspace; required to assign Azure AI Owner (PlatformAdministrator) or Azure AI User (Scientist) at RG scope |
| `-WorkspaceManagedRGSubscriptionId` | Optional | Subscription containing the workspace MRG (defaults to `-SubscriptionId`) |
| `-AllowIncomplete` | Optional | Suppress PartialSuccess (exit 2) when the Azure AI Owner/User role is intentionally skipped |
| `-SkipModuleInstall` | Optional | Skip auto-install of Az modules (CI/restricted environments) |
| `-Force` | Optional | Skip the confirmation prompt (automation/CI) |
| `-WhatIf` | Optional | Preview the plan without making any changes |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All assignments succeeded (or already existed) |
| 2 | Partial success — one or more roles were skipped or failed |
| 3 | Aborted before any changes (validation, permission, or no resolvable users) |
| 4 | Unhandled exception |

---

## Authentication

The script manages Azure sign-in automatically — you do **not** need to run `Connect-AzAccount` manually before executing it.

**If you are already signed in**, the script shows your current account and tenant, then offers you a chance to switch to a different tenant:

```
  Already signed in as: alice@contoso.com
  Current tenant:       xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

  Press ENTER to use the current tenant, or enter a different Tenant ID
  (needed when the subscription belongs to a different tenant):
  Tenant ID [xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx]:
```

Press **Enter** to keep the current tenant, or type a different tenant GUID and press Enter.

**If you are not signed in**, the script optionally asks for a tenant ID before launching the `Connect-AzAccount` browser flow:

```
  Enter the Tenant ID to sign in to (press ENTER to let Azure resolve it automatically):
  Tenant ID:
```

**For automation / CI**, pass `-TenantId` as a parameter to skip both prompts entirely.

### Cross-tenant subscriptions

If your subscription lives in a **different tenant** than your default sign-in, MFA errors like the following will appear unless you specify the correct tenant:

```
Unable to acquire token for tenant '...' ... User interaction is required.
```

Fix: pass the subscription's tenant GUID via `-TenantId` (or enter it at the prompt).

```powershell
./Set-DiscoveryRoleAssignments.ps1 `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -TenantId "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy" `
    -Persona PlatformAdministrator `
    -Scope Subscription `
    -UserIds "alice@contoso.com"
```

---

## Usage

### Interactive (recommended for first-time use)

```powershell
./Set-DiscoveryRoleAssignments.ps1
```

The script will prompt for: SubscriptionId → Persona → UserIds → Scope → ResourceGroupName (if RG) → WorkspaceManagedRGName (if RG).

### Subscription scope — Platform Administrator

```powershell
./Set-DiscoveryRoleAssignments.ps1 `
    -Persona PlatformAdministrator `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -Scope Subscription `
    -UserIds "alice@contoso.com","bob@contoso.com"
```

### Resource Group scope — Scientist

> Assumes ACR, Storage, VNET, MI, and the workspace are all in `contoso-discovery-rg`.

```powershell
./Set-DiscoveryRoleAssignments.ps1 `
    -Persona Scientist `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -Scope ResourceGroup `
    -ResourceGroupName "contoso-discovery-rg" `
    -WorkspaceManagedRGName "contoso-discovery-mrg" `
    -UserIds "scientist1@contoso.com;scientist2@contoso.com"
```

### Dry-run preview

```powershell
./Set-DiscoveryRoleAssignments.ps1 `
    -Persona PlatformAdministrator `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -Scope Subscription `
    -UserIds "alice@contoso.com" `
    -WhatIf
```

### Guest user by Object ID

```powershell
./Set-DiscoveryRoleAssignments.ps1 `
    -Persona Scientist `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -Scope ResourceGroup `
    -ResourceGroupName "contoso-discovery-rg" `
    -UserIds "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
```

### CI / automation

```powershell
./Set-DiscoveryRoleAssignments.ps1 `
    -Persona Scientist `
    -SubscriptionId "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" `
    -Scope Subscription `
    -UserIds "user1@contoso.com","user2@contoso.com" `
    -SkipModuleInstall `
    -Force `
    -AllowIncomplete
```

---

## Two-step workflow when the workspace doesn't exist yet (RG scope)

The Workspace Managed RG (MRG) is created **only after** the Discovery workspace is provisioned. If you run the script before the workspace exists, the **Azure AI Owner/User** role will be skipped.

1. **Step 1 — pre-create roles:** run the script without `-WorkspaceManagedRGName`. When prompted to include the AI role, answer **N**. All other roles are assigned; the AI role is reported as Skipped.
2. **Create the Discovery workspace** in the portal/CLI/Bicep. Note the generated Managed Resource Group name.
3. **Step 2 — finish AI role:** rerun the script with `-WorkspaceManagedRGName <mrg-name>`. The script prints a ready-to-paste rerun command at the end of step 1 to make this easy. Already-assigned roles are detected and reported as `AlreadyAssigned` (idempotent).

> Tip: with `-Scope Subscription`, the AI role is assigned at subscription scope alongside the others, so this two-step workflow isn't needed.

---

## Output

After execution, the script prints three clearly separated sections:

- **ASSIGNED ROLES** — successfully assigned, already in place, or planned (in `-WhatIf`).
- **ROLES THAT COULD NOT BE ASSIGNED (FAILED)** — includes the underlying error per row.
- **SKIPPED ROLES** — with the reason (e.g. missing MRG name, role not yet available in tenant).

Long UPNs are aliased (`U1`, `U2`, …) with a legend printed below the tables to keep rows readable.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `FATAL: -ResourceGroupName is required when -Scope is 'ResourceGroup'.` | Pass `-ResourceGroupName <name>` or choose `-Scope Subscription`. |
| `Role 'Microsoft Discovery Bookshelf Index Data Reader - Preview' not found in this tenant.` | The role hasn't propagated to the tenant yet. The run continues; rerun later to pick it up. |
| `Azure AI Owner/User ... [-WorkspaceManagedRGName not provided; ...]` | Workspace not created yet. Follow the two-step workflow above, or use `-Scope Subscription`. |
| `Permission denied` from `New-AzRoleAssignment` | Executor lacks Owner / User Access Administrator / RBAC Administrator at the target scope. |
| Wrong role got assigned in earlier runs (Platform Reader instead of Bookshelf) | Older versions of the script had a hardcoded GUID bug. Remove the stale assignment with `Remove-AzRoleAssignment` and rerun. |
| `Unable to acquire token for tenant '...' — User interaction is required` | Subscription is in a different tenant. Pass `-TenantId <guid>` or enter the tenant GUID at the prompt. See [Authentication](#authentication). |
| `FATAL: Could not set context to subscription '...': Please provide a valid tenant or a valid subscription.` | No valid context for the subscription's tenant. Pass `-TenantId` with the correct tenant GUID. |

---

## Idempotency

Running the script multiple times is safe. Any role assignment that already exists is detected and reported as `AlreadyAssigned` rather than re-created.
