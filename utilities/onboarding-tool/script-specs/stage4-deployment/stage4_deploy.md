# stage4_deploy — Stage 4 deployment (consolidated)

Stage 4 · single consolidated PowerShell 7 + Az CLI script · FR mapping: FR4.1–FR4.6
Script: `../../scripts/stage4-deployment/stage4_deploy.ps1`

## Purpose
Deploy the platform in dependency order and, when a step fails, surface the true cause with a specific remediation instead of a raw ARM error. Gated on a green Stage 3 report. Uses api-version 2026-06-01 for all `Microsoft.Discovery` ARM resources and the workspace data plane.

## Inputs
- `--config <config.json>`, the green readiness report. Optional `--no-bicep` to force the per-resource ARM PUT sequence, or a custom `--bicep-path` / `--parameters-path`.
- Recovery mode: `--recovery --subscription --resource-group --workspace`.

## Deploy method
Deploy via a Bicep template (`discovery-platform.bicep`) by default, with parameters generated from the config (subnet ids by role, managed identity, storage account, names, regions, bookshelf scope, and `network.outboundType`). The per-resource ARM PUT sequence is retained behind `--no-bicep` and is also used to gate each resource on Succeeded and to drive true-state detection and remediation after the deployment.

The supercomputer `outboundType` comes from the Stage 1 planning decision `network.outboundType` (default `UserDefinedRouting`); it is passed straight through to the `outboundType` template parameter. `UserDefinedRouting` (forced tunneling) requires the managedcluster subnet to carry the `Microsoft.ContainerService/managedClusters` delegation and egress to route through the customer firewall/NVA.

## Behavior
- Deploy in order, gating each on Succeeded, then run true-state detection and, on failure, the error-remediation engine.
- Log resource, provisioning state, and matched remediation; exit non-zero (FR4.6).
- Offer the targeted re-PUT recovery path for a workspace-only failure.

## Output
- JSON: per-step resource + state + remediation.
- Human: ordered deploy log with the go/no-go at each gate.

## Exit codes
- 0 = all steps green.
- Non-zero = at least one failure (see report).

## Folded steps
Each concern ran as a separate sub-script before consolidation; the logic now lives in `stage4_deploy.ps1`. This stage and Stage 2 are the only writers of platform resources.

### deploy_order — FR4.1, FR4.2
Deploy in dependency order and gate each on Succeeded: supercomputer → workspace (`properties.supercomputerIds`) → chat model → project → bookshelf. If the supercomputer is Failed, do not touch the workspace. Create the validation chat-model deployment named `gpt-5-4` (model gpt-5.4) explicitly — the cognition deployment is auto-provisioned at workspace creation, but without gpt-5-4 the Discovery Engine cannot validate task results and will not start. Use api-version 2026-06-01 for all Discovery resources and the data plane; the tools-only 2026-02-01-preview is superseded.
- Supercomputer Failed: fix it before the workspace.
- Engine will not start: confirm the manual gpt-5-4 deployment exists.

Region co-location (pre-flight): the supercomputer `location` (from `controlPlaneRegion`) must equal the region of the BYO VNet that holds the managedcluster/nodepool subnets. Discovery validates the node pool `SubnetId` against the supercomputer's primary region, and `discovery.overridemrgregion` (workloadRegion) does not relax that check. The chosen region must also be a Discovery-creatable region: creation is rejected in some regions (e.g. eastus2 returns "Creation of new Supercomputer resources is not supported in region") even though the ARM provider location list advertises them; eastus is confirmed creatable. So the BYO VNet must live in a creatable region. The script resolves the VNet region from the subnet id and fails fast with a RegionMismatch remediation before the PUT. Region is immutable, so a mismatch requires setting `controlPlaneRegion` to a creatable VNet region, deleting the failed supercomputer, and re-running (a plain re-PUT cannot move it).
- RegionMismatch on SubnetId: set controlPlaneRegion = the managedcluster/nodepool VNet region (which must itself be a Discovery-creatable region); delete the failed supercomputer and re-run.
- Creation not supported in region: the region is not Discovery-creatable for this resource type; place the BYO VNet and set controlPlaneRegion to a creatable region (eastus confirmed; eastus2 rejected despite being advertised).

### true_state_detection — FR4.3
Catch the case where the ARM resource list shows Succeeded while a Foundry account is still Creating: confirm Foundry state with `az cognitiveservices account show`, and enforce a timeout that converts a stuck Accepted/Creating into a terminal failure.
- Stuck Creating past timeout: treat as failed; purge/retry per the error-remediation mapping.

### error_remediation_engine — FR4.4
Match the ARM error signature and emit the specific remediation:
- `Creation of new X resources is not supported in region` → the target region is not Discovery-creatable for that resource type (ARM advertises more locations than the service allows) → deploy into a creatable region (eastus confirmed; eastus2 rejected) and place the BYO VNet there so the supercomputer stays co-regional with its node pool subnet.
- `RegionMismatch` on supercomputer/nodePool `SubnetId` → supercomputer location differs from the BYO VNet/subnet region → set controlPlaneRegion to the VNet region so the supercomputer is co-regional with its subnets, delete the failed supercomputer, and re-run (region is immutable).
- `AKSCapacityHeavyUsage` / `InternalServerError` on AKS create → region capacity for API Server VNet Integration → retry, or deploy workload in a region with capacity and global-peer to the firewall.
- Repeated `AZFWApplicationRule` deny on packages.microsoft.com → firewall source scoped to the wrong CIDR → add the real spoke CIDR and allow the bootstrap FQDNs.
- 409 `FlagMustBeSetForRestore` → Foundry account soft-deleted then recreated → set Restore=true, or purge and wait before re-PUT.
- `RequestDisallowedByPolicy` on Foundry/Cognitive Services → workspace-MRG account with publicNetworkAccess=Enabled → apply the workspace-MRG exemption.
- `RequestDisallowedByPolicy` on Log Analytics → apply the LA MRG public-access exemption.
- Storage public-access policy deny → apply the Bookshelf MRG exemption, or move to PE architecture.
- No CustomDnsConfigs found on PE → approve the PE (Pending) or recreate (Rejected/Disconnected); success = Approved, dnsCount 3.
- NSP association `InternalServerError`, terminal Failed → retry with backoff after convergence.
- Unmatched signature: log the raw error and flag for the dependency-spec owner to add a mapping.

### recovery_reput — FR4.5
Provide the targeted re-PUT path for a workspace-only failure: re-PUT the workspace reusing the existing Succeeded supercomputer, then create chat model then project in that order (project depends on chat model).
- Re-PUT still fails: check the supercomputer is Succeeded and the FR2.1a NSP joiner role is assigned.
