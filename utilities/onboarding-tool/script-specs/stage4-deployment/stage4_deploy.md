# stage4_deploy — Stage 4 deployment (consolidated)

Stage 4 · single consolidated PowerShell 7 + Az CLI script · FR mapping: FR4.1–FR4.6
Script: `../../scripts/stage4-deployment/stage4_deploy.ps1`

## Purpose
Deploy the platform in dependency order and, when a step fails, surface the true cause with a specific remediation instead of a raw ARM error. Supplied Stage 3 reports must be GO; omitting the reports or supercomputer profile coverage only produces a warning. Reports are not bound to the current config, and static GO does not prove working egress. Uses api-version 2026-06-01 for all `Microsoft.Discovery` ARM resources and the workspace data plane.

## Inputs
- `-ConfigPath <config.json>`, optional `-ReadinessReport` with one or more GO report paths. Optional `-NoBicep` to force the per-resource ARM PUT sequence, or a custom `-BicepPath` / `-ParametersPath`.
- Recovery mode: `-Recovery -Subscription <id> -ResourceGroup <name> -Workspace <name>`.

## Deploy method
Deploy via a Bicep template (`discovery-platform.bicep`) by default, with parameters generated from the config (subnet ids by role, managed identity, storage account, names, regions, workspace network settings, and `network.outboundType`). Every project is linked to a storage container regardless of Bookshelf scope. The container is named `names.storageContainer`; when that's blank, Stage 4 appends `-storage` to a workspace-name prefix and truncates that prefix as needed to keep the derived name within 24 characters. It reuses an existing valid `<workspace>-bookshelf` container created by earlier releases, so reruns keep the same project container. The per-resource ARM PUT sequence is retained behind `-NoBicep` and is also used to gate each resource on Succeeded and to drive true-state detection and remediation after the deployment.

Stage 4 validates that `names.workspace` is nonblank before deriving any default resource name or
submitting a deployment. A missing workspace is returned as the structured
`deploy-config-workspace` failure, including under `-PassThru`.

The supercomputer `outboundType` comes from the Stage 1 planning decision `network.outboundType` (default `UserDefinedRouting`); it is passed straight through to the `outboundType` template parameter. `UserDefinedRouting` (forced tunneling) requires egress to route through the customer firewall/NVA and a separate management subnet (spare role / `managementSubnet`, delegated to `Microsoft.ContainerService/managedClusters`) passed as `managementSubnetId` for AKS API-server VNet integration. With `LoadBalancer`, `managementSubnetId` is omitted. The managedcluster subnet itself must never be delegated; the `deploy-subnet-topology` pre-flight enforces both rules before submit.

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
Deploy in dependency order and gate each on Succeeded: supercomputer → workspace (`properties.supercomputerIds`) → chat model → project storage container → project. The tool does not deploy Bookshelf or ingest its content, even when `bookshelf.inScope=true`. If the supercomputer is Failed, do not touch the workspace. Create the validation chat-model deployment named `gpt-5-4` (model gpt-5.4) explicitly — the cognition deployment is auto-provisioned at workspace creation, but without gpt-5-4 the Discovery Engine cannot validate task results and will not start. Use api-version 2026-06-01 for all Discovery resources and the data plane; the tools-only 2026-02-01-preview is superseded.
- Supercomputer Failed: fix it before the workspace.
- Engine will not start: confirm the manual gpt-5-4 deployment exists.

After the project step, grant Foundry roles on the workspace managed resource group
(`properties.managedResourceGroup`):

- Foundry Owner (`c883944f-8b7b-4483-af10-35834be79c4a`) to Platform Administrator principals,
  or to `deployingIdentity` when none are configured.
- Foundry User (`53ca6127-db72-4b80-b1b0-d745d6d5456d`) to Platform Contributor principals.

With `customer-jit-managed`, Stage 4 creates or reuses PIM eligibility for users and reminds them
to activate the role. Eligible-but-inactive does not fail the completed deployment. Service
principals and managed identities keep standard assignments. Other assignment failures are Warn.
The workspace `publicNetworkAccess` comes from `workspace.publicNetworkAccess` (default `Enabled`) and is applied on the bicep deploy, the direct workspace PUT, and the recovery re-PUT.
The immutable `NetworkIsolation` tag comes from `workspace.networkIsolation` (default `true`) and is applied by both Bicep and direct workspace deployment.
Region co-location (pre-flight): the supercomputer `location` (from `controlPlaneRegion`) must equal the region of the BYO VNet that holds the managedcluster/nodepool subnets. Discovery validates the node pool `SubnetId` against the supercomputer's primary region, and `discovery.overridemrgregion` (workloadRegion) does not relax that check. The chosen region must also be a Discovery-creatable region: creation is rejected in some regions (e.g. eastus2 returns "Creation of new Supercomputer resources is not supported in region") even though the ARM provider location list advertises them; eastus is confirmed creatable. So the BYO VNet must live in a creatable region. The script resolves the VNet region from the subnet id and fails fast with a RegionMismatch remediation before the PUT. Region is immutable, so a mismatch requires setting `controlPlaneRegion` to a creatable VNet region, deleting the failed supercomputer, and re-running (a plain re-PUT cannot move it).
- RegionMismatch on SubnetId: set controlPlaneRegion = the managedcluster/nodepool VNet region (which must itself be a Discovery-creatable region); delete the failed supercomputer and re-run.
- Creation not supported in region: the region is not Discovery-creatable for this resource type; place the BYO VNet and set controlPlaneRegion to a creatable region (eastus confirmed; eastus2 rejected despite being advertised).

### true_state_detection — FR4.3
Allow 15-30 minutes for the supercomputer and up to about an hour for the workspace; plan one to two hours overall. Deployment/recovery callers use a 120-minute resource-state polling timeout per resource; this is not a guaranteed completion time.

Catch the case where the ARM resource list shows Succeeded while a Foundry account is still Creating: confirm Foundry state with `az cognitiveservices account show`, and enforce a timeout that converts a stuck Accepted/Creating into a terminal failure. The Foundry state only tightens the gate: the step passes when both the ARM state and the Foundry state are Succeeded, and a Failed ARM state is never overridden by a Succeeded Foundry account.
- Stuck Creating past timeout: treat as failed; purge/retry per the error-remediation mapping.
- Workspace Failed: the RP returns a generic InternalServerError, so read the failed operations from the workspace managed RG activity log and match those against the remediation engine.

### error_remediation_engine — FR4.4
Match the ARM error signature and emit the specific remediation:
- `InsufficientQuota` (Tokens Per Minute) on a managed-RG model deployment → not enough free gpt-5.4 GlobalStandard TPM in the workload region (workspace needs 250K, the chat model 200K) → free or request quota, then re-run (Stage 1 `model-quota` catches this up front).
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
