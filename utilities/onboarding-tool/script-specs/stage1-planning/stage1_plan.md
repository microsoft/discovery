# stage1_plan — Stage 1 planning (consolidated)

Stage 1 · single consolidated PowerShell 7 + Az CLI script · FR mapping: FR1.0–FR1.8
Script: `../../scripts/stage1-planning/stage1_plan.ps1`

## Purpose
Drive the planning sheet end to end: load the filled network-planning form, run every embedded validation, and emit the single machine-readable config only when all checks pass or carry a recorded waiver. This config is the single source of truth for Stages 2–5.

## Inputs
- `--form <network-planning-form.xlsx|.json>` filled by the customer.
- `--out <config.json>` target path for the exported config.
- `--waivers <waivers.json>` optional, justifications for overridden checks.

## Behavior
- Parse the form into the in-memory config model (`config.schema.json`). A `.json` input is filled with the planning form's defaults for any missing field (for example `network.model=byo`, `network.outboundType=UserDefinedRouting`, `storage.model=byo`, `workspace.publicNetworkAccess=Enabled`). A missing `resourceGroup` falls back to `network.networkResourceGroup`; a missing `network.dnsResourceGroup` tells later stages to use `network.networkResourceGroup` for private DNS. Values present in JSON always win.
- Require `rbac.humanAccessMode`. `permanent-role-assignments` creates standard User assignments. `customer-jit-managed` requires `rbac.jitEligibilityDurationDays` to be a whole number from 7 through 3650 and makes Stages 2 and 4 create PIM eligibility with `AdminAssign`.
- Treat eligibility and activation separately. The tool creates eligibility; customers activate user roles. Workload-identity assignments remain persistent.
- Run each folded check in order; collect per-check pass/fail plus remediation.
- Block export if any P0 check fails without a matching waiver entry.
- Write the validated config, stamped with schema version and content hash.

## Output
- JSON: aggregate check results plus the exported config path.
- Human: a per-check table (check, status, remediation) and a go/no-go verdict.

## Exit codes
- 0 = all checks green.
- Non-zero = at least one failure (see report).

## Folded checks
Each check ran as a separate sub-script before consolidation; the logic now lives in `stage1_plan.ps1`. Every failed check carries its own remediation string.

### subscription_prereq — FR1.0
Confirm the subscription is allowlisted for Discovery, record the RP-registration requirement (registration happens in Stage 2), and verify the deploying identity holds Contributor/Owner or a custom role with `Microsoft.Discovery/register/action`.
- Not allowlisted: request Discovery enablement from the Microsoft Discovery team before proceeding.
- Identity lacks register rights: grant Contributor/Owner or a role with `Microsoft.Discovery/register/action`.

### capture_fields — FR1.1
Capture and normalize control-plane region, workload region, VNet CIDR, per-service subnet CIDRs, BYO storage model, deploying identity, and policy set. Normalize regions to Azure short names and CIDRs to canonical form; flag any required field left blank.
- Missing field: complete the corresponding cell in the planning sheet.

### project_storage — FR1.1
Require `storage.model=byo` with `storage.account` or `storage.accountId` for every deployment. Every project requires a Discovery storage container backed by a customer storage account, independently of whether Bookshelf is in scope. The customer pre-creates the account; the tool doesn't create it. When logged in, look the account up in the target subscription, fail if it doesn't exist, and write its resource ID to `storage.accountId` in the exported config so Stages 2 and 4 target the right resource group.
- Missing project storage: enter the name of a pre-created StorageV2 account in the `storage.account` cell of the planning form (keep `storage.model=byo`; a blank or absent model defaults to `byo`). The remediation includes the `az storage account create` command. `storage.accountId` is for JSON configs only; the form doesn't expose it.

### workspace_public_access — FR1.2
Validate `workspace.publicNetworkAccess` is `Enabled` (default) or `Disabled`. Stage 4 applies it to the workspace. `Disabled` is valid and reported as Pass, with a note that Stage 5 must run from inside the VNet.
Capture `workspace.networkIsolation` as a boolean (default `true`). Stage 4 maps it to the immutable `NetworkIsolation` workspace tag. When enabled, Workbench access requires VPN or ExpressRoute even if `workspace.publicNetworkAccess=Enabled`.
- Invalid value: set `Enabled` or `Disabled`.

### subnet_sizing — FR1.2
Check each Discovery subnet meets its required prefix (agent /26, workspace /26, search /27, AKS managed cluster /26, AKS node pool /26 ×2, private endpoints /27, spare /27) and delegation (container-app subnets → `Microsoft.App/environments`; managed cluster → none, because the supercomputer system nodes run there; spare/management → `Microsoft.ContainerService/managedClusters` when `outboundType=UserDefinedRouting`, otherwise either; others none). Confirm the packed layout fits a /23; offer the /24 agent-subnet fallback where a region rejects the packed layout.
- Prefix too small: resize the subnet to the required prefix.
- Wrong/missing delegation: set the delegation in the table.
- Region rejects packed layout: switch to the /24 agent-subnet fallback.

### egress_model — FR1.2
Capture `network.outboundType`, the AKS egress model, at planning time: `UserDefinedRouting` (forced tunneling via the customer firewall/NVA next-hop) or `LoadBalancer` (Azure-managed egress). Stage 4 passes this to the supercomputer.
- `UserDefinedRouting` with blank `network.nvaNextHop`: provide the firewall/NVA next-hop IP so Stages 2–3 can build and validate the egress route.
- Invalid value: set `network.outboundType` to `UserDefinedRouting` or `LoadBalancer`.

### address_space_conflict — FR1.3
Detect any Discovery subnet overlapping an existing subnet and confirm the full layout fits the free space in the VNet.
- Overlap: relocate the Discovery subnet to a free range.
- Insufficient space: widen the VNet or reduce non-Discovery usage.

### byo_subnets — FR1.3
For `network.model=byo-existing`, match each planned subnet to an existing subnet in the VNet by CIDR and record its name in the exported config. Stages 2 and 4 use that name instead of `snet-<role>`.
- Unmatched role/CIDR: correct the SUBNET row CIDR, or create the subnet in the VNet.

### region_availability — FR1.4
Confirm the workload region offers required features, and distinguish capacity from quota. Flag AKS API Server VNet Integration capacity (`AKSCapacityHeavyUsage` seen in eastus2) and AI Search regional capacity; recommend the workload/control-plane split where a region is capacity-limited.
- Capacity-limited region: split control plane and workload, or choose a region with capacity and global-peer to the firewall.

### quota_sku — FR1.5
Expand the sizing tier (Small|Medium|Large) into concrete resource counts and required quota, then validate:
- Effective Stage 4 VM SKUs are offered in-region and unrestricted for the configured subscription. Defaults are a 3-node `Standard_D4s_v6` system pool and a node pool scaling from 0 to 3 `Standard_D4ds_v6` nodes; advanced JSON configs can override `systemSku`, `nodePoolVmSize`, and `nodePoolMaxNodeCount`.
- Total Regional and VM-family quota are calculated from the live vCPU/family metadata of those effective SKUs. System-pool shortfalls fail the gate; node-pool scale-out shortfalls warn because initial deployment can still succeed.
- Cosmos autoscale RU/s: workspace 2,400 (max 4,000); each project 400 (max 4,000); sized 2,400 + 400 × projects.
- Model TPM: GPT-5.4 workspace/cognition 250K plus gpt-5-4 validation chat 200K, requiring 450K free for a fresh deployment; resumed deployments count only missing allocations. Bookshelf planning estimates per instance are GPT-5.2 200K, GPT-5 Mini 2M and Text Embedding 3 Small 2M, but the current quota check validates only GPT-5.4.
- Bookshelf on-demand nodepool by tier (Small D48s_v6, Medium D128s_v6, Large D192s_v6) plus always-on AI Search S1 and an ACA dedicated profile.
- Global Standard vs Data Zone Standard where the config requires data residency.
- Quota gap: file the increase (feeds Stage 2 quota_exemption_requests).
- SKU not in region: switch to the in-region SKU.
- TPM shortfall: raise the deployment TPM or free existing capacity. Check `model-quota` confirms
  that the regional model catalog exposes an OpenAI gpt-5.4 version with a GlobalStandard SKU whose
  usage name is `OpenAI.GlobalStandard.gpt-5.4`. Selection mirrors the deployment resolver: filter
  by model and SKU first, prefer a compatible default version, then fall back to the latest
  compatible version. The workspace can use a service-pinned version independently. The check
  confirms from SKU rate-limit metadata that each quota capacity unit represents 1,000 tokens per
  minute before interpreting usage values as K TPM. Every query is pinned to `subscriptionId` and
  forces JSON output. A fresh deployment needs 450K (workspace 250K + chat model 200K); a resumed
  deployment counts only allocations whose Discovery resources are not already `Succeeded`.
  Quota is scoped by subscription, region, model, and deployment type. A numeric quota row by
  itself does not prove deployability. `Blocked` and `InOverage` are failures; unknown statuses and
  unreadable/malformed results are unverified warnings during planning and blocking failures in
  Stage 3 unless explicitly waived. Soft-deleted Foundry accounts can keep regional quota, but
  purging is permanent and requires owner confirmation.

### naming_validation — FR1.6
Enforce per-type naming rules (lowercase alphanumeric + hyphens, start with a letter, no consecutive separators) and length limits (workspace 3–24, project 3–12, supercomputer 3–24, node pool 3–12, tool 3–24, agent 3–63, storage container 3–24, storage asset 3–24, investigation 1–20). Reserve MRG names (`mrg-dwsp-<workspace>-<6char>`, `mrg-dscmp-<supercomputer>-<6char>`, `mrg-dbksf-<bookshelf>-<6char>`) and call `Microsoft.Discovery/checkNameAvailability` for workspace uniqueness (the workspace name is the endpoint subdomain).
- Rule violation: rename per the per-type rule shown.
- Workspace name taken: choose another (it is the public subdomain).

### policy_preflight — FR1.7
Collect the policy assignments effective at the target subscription (including inherited management-group assignments) with `az policy assignment list --disable-scope-strict-match`, resolving each assignment's type (BuiltIn/Custom) and effect. A parameterized effect (`[parameters('effect')]`) resolves to the assignment's value, else the definition's default. Cross-check declared + live assignment names against the known Discovery blockers (Cognitive Services public access, Log Analytics public access, Storage public/network access, NSP association) and classify each as exemption vs configuration change (`policy-preflight`). Live assignments whose effect is Audit, AuditIfNotExists or Disabled can't block a deployment and are ignored. Storage policies unrelated to network access (for example, shared-key access) aren't blockers; the tool doesn't create the storage account, and Discovery works with shared keys disabled. Separately surface custom restrictive policies — effect deny/denyAction/modify/deployIfNotExists/append (`policy-collect`) — so customer-specific blockers are caught before Stage 2.
- Blocking deny policy: plan the exemption or configuration change (feeds Stage 2 quota_exemption_requests).
- Custom restrictive policy: review against the Stage 2 subnet/NSG/route/DNS/storage plan.
- az not logged in: `policy-collect` skips; run `az login` to collect the live set.

### config_export — FR1.8
Emit the config export only when all embedded validations pass or are explicitly waived with a recorded justification. Refuse to export if any P0 check is red without a waiver; write against `config.schema.json`, embed the waiver list, and stamp schema version and content hash.
- Export blocked: resolve the named red check or add a waiver with justification, then re-run.
