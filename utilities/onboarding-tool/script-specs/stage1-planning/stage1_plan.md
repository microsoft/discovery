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
- Parse the form into the in-memory config model (`config.schema.json`).
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

### subnet_sizing — FR1.2
Check each Discovery subnet meets its required prefix (agent /26, workspace /26, search /27, AKS managed cluster /26, AKS node pool /26 ×2, private endpoints /27, spare /27) and delegation (container-app subnets → `Microsoft.App/environments`, managed cluster → `Microsoft.ContainerService/managedClusters`, others none). Confirm the packed layout fits a /23; offer the /24 agent-subnet fallback where a region rejects the packed layout.
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

### region_availability — FR1.4
Confirm the workload region offers required features, and distinguish capacity from quota. Flag AKS API Server VNet Integration capacity (`AKSCapacityHeavyUsage` seen in eastus2) and AI Search regional capacity; recommend the workload/control-plane split where a region is capacity-limited.
- Capacity-limited region: split control plane and workload, or choose a region with capacity and global-peer to the firewall.

### quota_sku — FR1.5
Expand the sizing tier (Small|Medium|Large) into concrete resource counts and required quota, then validate:
- VM SKUs offered in-region (`Standard_D4s_v6` not in eastus/eastus2; use `Standard_D4ds_v6`).
- Cosmos autoscale RU/s: workspace 2,400 (max 4,000); each project 400 (max 4,000); sized 2,400 + 400 × projects.
- Model TPM: GPT-5.4 cognition 250k min, gpt-5-4 validation 200k min, Agents 200k min, ≥500k GPT-5.4 free. Bookshelf per instance: GPT-5.2 200k, GPT-5 Mini 2M, Text Embedding 3 Small 2M.
- Bookshelf on-demand nodepool by tier (Small D48s_v6, Medium D128s_v6, Large D192s_v6) plus always-on AI Search S1 and an ACA dedicated profile.
- Global Standard vs Data Zone Standard where the config requires data residency.
- Quota gap: file the increase (feeds Stage 2 quota_exemption_requests).
- SKU not in region: switch to the in-region SKU.
- TPM shortfall: raise the deployment TPM or free existing capacity.

### naming_validation — FR1.6
Enforce per-type naming rules (lowercase alphanumeric + hyphens, start with a letter, no consecutive separators) and length limits (workspace 3–24, project 3–12, supercomputer 3–24, node pool 3–12, tool 3–24, agent 3–63, storage container 3–24, storage asset 3–24, investigation 1–20). Reserve MRG names (`mrg-dwsp-<workspace>-<6char>`, `mrg-dscmp-<supercomputer>-<6char>`, `mrg-dbksf-<bookshelf>-<6char>`) and call `Microsoft.Discovery/checkNameAvailability` for workspace uniqueness (the workspace name is the endpoint subdomain).
- Rule violation: rename per the per-type rule shown.
- Workspace name taken: choose another (it is the public subdomain).

### policy_preflight — FR1.7
Collect the policy assignments effective at the target subscription (including inherited management-group assignments) with `az policy assignment list --disable-scope-strict-match`, resolving each assignment's type (BuiltIn/Custom) and effect. Cross-check declared + live assignment names against the known Discovery blockers (Cognitive Services public access, Log Analytics public access, Storage public access, NSP association) and classify each as exemption vs configuration change (`policy-preflight`). Separately surface custom restrictive policies — effect deny/denyAction/modify/deployIfNotExists/append (`policy-collect`) — so customer-specific blockers are caught before Stage 2.
- Blocking deny policy: plan the exemption or configuration change (feeds Stage 2 quota_exemption_requests).
- Custom restrictive policy: review against the Stage 2 subnet/NSG/route/DNS/storage plan.
- az not logged in: `policy-collect` skips; run `az login` to collect the live set.

### config_export — FR1.8
Emit the config export only when all embedded validations pass or are explicitly waived with a recorded justification. Refuse to export if any P0 check is red without a waiver; write against `config.schema.json`, embed the waiver list, and stamp schema version and content hash.
- Export blocked: resolve the named red check or add a waiver with justification, then re-run.
