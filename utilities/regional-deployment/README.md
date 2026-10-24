# Opt-in regional fallback for Discovery services

This optional **Python 3.10+ / Azure CLI / Bicep** utility helps operators recover from
verified regional quota or capacity blockers. It does not change the existing
five-stage PowerShell onboarding flow or automatically relocate resources.

It provides two explicit deployment boundaries:

| Mode | Placement and preservation |
| --- | --- |
| `fresh` | If the source compute has not succeeded, generate a new complete stack in an explicitly named **different RG** and selected workload region. Preserve the source RG; do not migrate its data or delete partial resources. |
| `workspace` | If the original Supercomputer, node pool and Discovery StorageContainer have succeeded, retain them and the private customer storage. Create only a new Workspace-side network, identity and platform resources in another workload region. The Discovery ARM control-plane region remains unchanged. |

The Workspace mode moves the **workspace managed dependency unit**, including its
Search/Foundry/Cosmos services. Discovery does not expose an independent Search
region or Search resource ID in this API. No unsupported per-service placement
field is invented here.

## Safety and prerequisites

- Use Azure **public cloud**, an enabled Discovery subscription and Discovery API
  `2026-06-01`. Current control-plane choices are `eastus`, `uksouth` and
  `swedencentral`; actual create support must still be checked.
- Install Python 3.10+, Azure CLI, Bicep and the Azure CLI `quota` extension.
  Python uses only its standard library. This utility does not need PowerShell.
- Sign in as the approved interactive user in the explicit subscription/tenant.
  Directory reads must resolve the user and Discovery first-party service principal.
- Provider, persona and first-party Reader/NSP prerequisites follow the
  [Discovery registration guide](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-resource-provider-registration)
  and [role assignments](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-role-assignments).
  `prepare --apply` writes Providers, the confirmed-missing RG and IAM, including a
  minimal subscription-scoped custom NSP role. Use approved Owner, or Contributor
  plus User Access Administrator, with required PIM access activated. Do not
  assume resource-write permission grants directory or role-definition authority.
- Review data residency, cross-region transfer charges, latency, peering and
  private DNS before `select --accept-cross-region`. GlobalStandard model
  processing is not guaranteed to remain in the resource's region.
- No automatic deletion, quota application, policy exemption, public-storage
  enablement, NSP skip tag, agent creation, inference or scientific job is included.
- Keep configuration, reports, user/tenant information and command evidence in
  ignored `out/`. Never commit tokens, storage keys, SAS or private evidence.

All examples below run from `utilities/regional-deployment`.

```bash
az login --tenant '<tenant-id>'
az account set --subscription '<subscription-id>'
az bicep version
az extension show --name quota
# If absent, install the quota extension under your approved tooling process:
# az extension add --name quota
```

## 1. Generate the original/default-region inputs

```bash
python3 regional_deploy.py init \
  --subscription '<subscription-id>' --tenant '<tenant-id>' \
  --resource-group discovery-primary --name-prefix discprimary \
  --control-plane-region eastus --workload-region eastus2 \
  --vnet-cidr 10.20.0.0/16 --output-dir out/primary
```

`init` writes a **new local directory only**, without Azure calls or overwrites.
The output is this utility's `deployment.config.json` and `parameters.json`, not
the Stage 1 PowerShell config format. Parameter paths are relative to the config's
directory; Bicep templates are fixed inside this utility.

For the ordinary new deployment, review the inputs, prepare prerequisites, then
run `preflight`, `validate`, and the explicitly approved deployment:

```bash
python3 regional_deploy.py prepare --config out/primary/deployment.config.json --apply
python3 regional_deploy.py preflight --config out/primary/deployment.config.json --stage full
python3 regional_deploy.py validate --config out/primary/deployment.config.json --stage full
# Review the saved JSON what-if before any actual deployment.
python3 regional_deploy.py deploy --config out/primary/deployment.config.json --stage full --apply
python3 regional_deploy.py wait --config out/primary/deployment.config.json --timeout 7200
```

When a prerequisite or deployment fails, stop. Do not automatically replay the
mutation or rerun a full foundation template against policy-managed networking.

### Adopt an existing deployment for recovery

Generate local source inputs with `init`, then set the **source** config and
parameter names/regions/CIDRs to the actual original resources before requesting
recommendations. Do not run `full` against that source to reconstruct it.

Important mappings from the PowerShell Stage 1 config:

| Existing Stage 1 field | This utility's source input |
| --- | --- |
| `subscriptionId`, target tenant, `resourceGroup` | Config `subscriptionId`, `tenantId`, `resourceGroup` |
| `controlPlaneRegion`, `workloadRegion` | Config `location`, `dataPlaneLocation`; parameters `location`, `overridemrgregion` must match |
| `names.supercomputer`, `names.nodePool`, `names.workspace` | Parameters `supercomputerName`, `nodePoolName`, `workspaceName` |
| `names.storageContainer`, `storage.account` | Parameters `storageContainerName`, `storageAccountName` |
| Actual network name/address space/PE subnet prefix | Parameters `vnetName`, `vnetAddressPrefix`, `privateEndpointSubnetPrefix` |

Workspace reuse currently requires one customer RG containing the retained
compute/store references, original VNet, storage account, Blob PE named
`pe-<storageAccountName>-blob`, and the original
`privatelink.blob.core.windows.net` zone. It verifies a single original Blob A
record. Centralized DNS in another RG, custom/multiple endpoint layouts,
cross-subscription/RG reuse and healthy-workspace migration require a separately
reviewed design; do not rename or recreate existing resources to fit this baseline.

## 2. Request read-only neighboring-region recommendations

```bash
python3 regional_deploy.py recommend \
  --config out/primary/deployment.config.json \
  --candidates centralus northcentralus \
  --report out/recommendations.json
```

Without `--failure-file`, the default-region probe must find a machine-verified
quota deficit or unavailable Standard Search offering before suggesting a move.
After a real failed allocation, also supply its fresh structured ARM error JSON
or deployment-operations JSON:

```bash
python3 regional_deploy.py recommend \
  --config out/primary/deployment.config.json \
  --failure-file /path/to/fresh-arm-error.json \
  --candidates centralus northcentralus \
  --report out/recommendations-after-failure.json
```

Readiness records for `model-quota` / `vcpu-quota` are accepted only when they
contain a numeric `available < required` deficit. Generic `InternalServerError`,
plain-text guesses, unreadable quota, `InvalidResourceType`, access failures and
policy failures do not justify relocation. A structured allocation failure may
justify fallback even when the catalog currently advertises a tier: catalogs are
not physical capacity reservations.

The report:

- Separates quota limits from physical allocation/capacity failures.
- Ranks candidates by Haversine distance using current subscription location
  coordinates, not a hard-coded neighbor/paired-region assumption. This distance
  is only a geographic heuristic, not a latency, residency or cost guarantee.
- Defaults to the same `geographyGroup`. Broader discovery requires the explicit
  `--allow-cross-geography` flag and a separate residency review at selection.
  `--candidates` is an optional operator-approved allowlist. `--limit` bounds live
  probes to 1–8 locations, default 3; this is not an exhaustive capacity search.
- Checks Standard Search offerings and exact tier-count quota; Container Apps
  environment quota; compatible OpenAI GPT-5.4 GlobalStandard catalog/rate-limit
  metadata and regional TPM; and VM SKU, regional/family vCPU quota when new
  compute is actually needed. Three system nodes and the configured maximum
  workload nodes are budgeted, with both VM families checked separately.
- Infers `workspace` scope when the exact source compute is Succeeded; otherwise
  it uses `fresh`. In-progress or unknown compute blocks fallback. It will not
  silently propose a duplicate of healthy compute.
- Marks unknown evidence as **not eligible**. It does not reserve capacity,
  prove all backing-service availability, validate organizational policy, or
  authorize a deployment.

Exit `0` means at least one candidate is eligible for the next preflight; `2`
means no candidate is verified/no actionable blocker. Runtime errors exit `1`.

Workspace-only recovery also requires a Succeeded node pool and StorageContainer.
It stops for a retained-compute quota/AKS blocker: relocating Workspace cannot fix
the original compute region's quota. Repair/request that quota, or separately
approve a genuinely new compute-stack plan; this utility does not move an existing
Supercomputer/node pool to another region or silently duplicate it.

## 3A. Select a fresh fallback stack

When the report scope is `fresh`, explicitly name a different target RG:

```bash
python3 regional_deploy.py select \
  --config out/primary/deployment.config.json \
  --recommendation out/recommendations.json --mode fresh --region centralus \
  --target-resource-group discovery-fallback --name-prefix discfallback \
  --vnet-cidr 10.60.0.0/16 --accept-cross-region --output-dir out/fallback
```

Selection writes local config/parameters only. It requires a recommendation
less than one hour old with unchanged source inputs/utility code and all selected
candidate checks passed. It preserves the control plane and workload shape,
uses new names, and never edits the source group. Review the new storage/account
plan: this is an isolated new stack, **not data migration**.

Use the same `prepare → preflight --stage full → validate --stage full →
deploy --stage full --apply → wait` sequence from section 1 against
`out/fallback/deployment.config.json`. All writes still require approval.

## 3B. Select a workspace-only cross-region recovery

When the report scope is `workspace`:

```bash
python3 regional_deploy.py select \
  --config out/primary/deployment.config.json \
  --recommendation out/recommendations.json --mode workspace --region centralus \
  --name-prefix discworkspace --vnet-cidr 10.60.0.0/16 \
  --accept-cross-region --output-dir out/workspace
```

The plan retains original Supercomputer/node pool/Discovery StorageContainer and
customer storage IDs. It generates a non-overlapping new VNet, workspace/agent/PE
subnets, NAT/IP, UAMI, four scoped workload roles, two global-VNet peerings and a
link from the new VNet to the **original** Blob DNS zone. The Workspace uses the
selected managed-resource region and references the retained compute/store.
There is no second customer storage account, Blob PE or A-record write, nor a PUT
of the retained VNet/compute/store. Service-managed backing accounts/endpoints for
the new Workspace remain service owned and can incur additional costs.
The new Project reuses output storage, not the old Workspace's agents,
conversations or Workbench state; those are not migrated. Retain old data-bearing
managed resources until their owners approve any later migration/cleanup.

If another Failed workspace owns the retained compute, specify its exact name
with `--source-workspace`. A Succeeded/in-progress source is not migrated.

### Explicit association release, only when needed

If the confirmed Failed source still owns the exact compute association, separately
review and approve the filtered source Workspace PUT:

```bash
python3 regional_deploy.py release-link \
  --config out/workspace/deployment.config.json --release-method put --apply
```

This preserves the source location/tags/UAMI/subnets and removes only the exact
compute link. It can retry service processing for the old failed Workspace; it is
not a harmless metadata-only operation. It never deletes the Workspace/compute,
does not detach healthy sources, and does not automatically retry a rejected
PATCH as a PUT. If the operation is ambiguous, GET the source/link and deployment
state before doing anything else. Do not run it when no release is required.

### New workspace-side foundation and platform

```bash
python3 regional_deploy.py preflight --config out/workspace/deployment.config.json --stage workspace
python3 regional_deploy.py validate --config out/workspace/deployment.config.json --stage workspace
# Review: exactly the planned 14 new/child resource IDs; no Modify/Delete.
python3 regional_deploy.py deploy --config out/workspace/deployment.config.json --stage workspace --apply
python3 regional_deploy.py wait --config out/workspace/deployment.config.json --timeout 7200
```

If the new foundation already succeeded, confirm its subnets, roles, NAT, peerings
and DNS link, then change only this config's `deploymentName` to a new `-core`
name. Run fresh preflight/validate/deploy with `--stage workspace-core` instead of
replaying the network. That stage writes only the exact Workspace/model/Project
IDs. It defaults to `workspace-core` for reuse configs. Incomplete foundations
must be reconciled with a separately reviewed minimal plan, not a blind full PUT.

## 4. Verify and initialize access

For either target config:

```bash
python3 regional_deploy.py verify --config out/workspace/deployment.config.json
python3 regional_deploy.py postconfigure --config out/workspace/deployment.config.json --apply
python3 regional_deploy.py audit --config out/workspace/deployment.config.json
```

For a fresh fallback, substitute `out/fallback/deployment.config.json`.
The templates create the six logical Discovery resources, including the Project
and chat-model deployment. `postconfigure` resolves the actual Workspace MRG and
verifies/adds Foundry User for the current user, reusing inherited coverage.
Audit checks actual states, IDs/relationships, required backing services,
approved endpoints, roles, private storage and, in reuse mode, peering/retention.
The authenticated project check is **GET agents only**, not inference.

Require both `audit.json` fields `ok=true` and
`authenticatedProjectReadSucceeded=true` for those respective checks. An
unreachable private API is separately recorded as WARN, not passed as reachable.
Private Workbench/Blob clients require an approved VPN/ExpressRoute, routing and
DNS design; this utility does not install a VPN, gateway transit or custom DNS
forwarding. Packet-level compute/tool execution and scientific certification are
separate tests and may be billable.

## Receipts, partial outcomes and limits

- Every environment has its own config-relative `.state/` receipts and timestamped
  `evidence/`. A new failed preflight/validation invalidates old success. Compiled
  template, filtered parameters, inputs, stage and utility-code hashes are bound
  to a one-hour deployment receipt.
- Default what-if policy rejects Modify, Delete, Unsupported and unknown results.
  Explicit `--allow-modify` permits reviewed changes, never Delete/Unsupported;
  the initial reuse foundation still cannot Modify anything. Reuse writes are
  additionally exact-ID allowlisted; resume compiled shapes are bounded.
- `status`/`wait` are read-only. An existing Running/Accepted deployment is not
  resubmitted; timeouts do not cancel Azure. There is no automatic mutation replay.
- Quota is checked only for missing model allocations on resume (baseline 250K
  workspace + 200K chat TPM). Existing Succeeded allocations are not double counted.
- Failed old MRGs/resources may remain billable. Inventory and cleanup are separate
  approved work; never delete the customer RG or shared compute/storage/DNS to
  clean up one failed Workspace.
- Live checks are necessary, not sufficient: service-selected model versions,
  Storage/Cosmos/other backing capacity, policy, role propagation and private data
  paths still need validation and post-deployment readback. No scientific or
  inference success is inferred from ARM success.

## Local validation

From the repository root:

```bash
python3 utilities/regional-deployment/check.py
# Python-only unit checks when Azure CLI/Bicep is unavailable:
python3 utilities/regional-deployment/check.py --skip-bicep
```

Tests use synthetic data, enforce a read-only query allowlist, and cover trigger
classification, distance/geography, quota units, partial-state selection, immutable
inputs, bounded writes and release guards. The default check also builds all four
Bicep templates and verifies the six-resource/14-resource/three-resource shapes.
It does not log in, run ARM what-if, create resources or send inference. Offline
validation is not an end-to-end deployment certification.

The code/template layout is self-contained: `regional_deploy.py` is the entry,
`capacity.py` handles read-only evidence, `inputs.py` local input generation,
`deploy.py` the guarded workflow, and `workspace.py` the retention workflow.
This utility does not import scripts from an operator's project directory.

## References

- [Infrastructure quickstart](https://learn.microsoft.com/en-us/azure/microsoft-discovery/quickstart-infrastructure?tabs=bicep) — baseline resource relationships and managed-region override.
- [Quota reservation](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-quota-reservation).
- [Private endpoint DNS integration](https://learn.microsoft.com/en-us/azure/private-link/private-endpoint-dns-integration).
- [Existing PowerShell onboarding user guide](../onboarding-tool/scripts/USER-GUIDE.md) — a separate interface and permission model; its configuration is not interchangeable with this utility.
