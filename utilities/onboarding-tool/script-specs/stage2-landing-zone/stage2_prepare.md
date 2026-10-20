# stage2_prepare — Stage 2 landing zone (consolidated)

Stage 2 · single consolidated PowerShell 7 + Az CLI script · FR mapping: FR2.1–FR2.9
Script: `../../scripts/stage2-landing-zone/stage2_prepare.ps1`

## Purpose
Turn the signed config into a deployed landing zone idempotently: identity, network, storage, private DNS, quota/exemption requests, and the firewall artifact.

## Inputs
- `-DryRun` optionally previews actions offline; `-JsonPath` writes plan reports unless `-PassThru` is set.
- `--config <config.json>` from Stage 1.
- `--subscription` / `--resource-group` targets.

## Behavior
- `-DryRun` reads and validates config offline, then describes the ordered actions and
  network/RBAC choices without Azure calls or request-artifact generation. Optional
  `-JsonPath` writes JSON and Markdown with verdict `PLAN` and `Skip` results.
  `-PassThru` returns plan results only. Exit 0 means plan generation, not a ready landing zone.
- Run the folded steps in dependency order: RP register → RBAC → NSP joiner role → network → NSG → routes → DNS → storage → artifacts.
- Converge on re-run without duplicate or conflicting resources (FR2.9).
- Stop and surface the first hard failure with its remediation.

## Output
- Dry run: `Skip` results and optional JSON/Markdown reports with verdict `PLAN`; no landing-zone or request artifacts.
- JSON: per-step resource plus provisioning state.
- Human: landing-zone build log and the generated request artifacts.

## Exit codes
- 0 = all live steps green, or offline plan generation succeeds with `-DryRun`.
- Dry run doesn't prove landing-zone readiness.
- Non-zero = a live step fails, or config loading or report writing fails. Config errors appear on the console without a plan.

## Folded steps
Each step ran as a separate sub-script before consolidation; the logic now lives in `stage2_prepare.ps1`. Only this stage and Stage 4 write platform resources.

### rp_register — FR2.1
Run `az provider register --namespace Microsoft.Discovery`, then verify each dependent RP reaches Registered: Microsoft.Network, Compute, Storage, ManagedIdentity, Authorization, CognitiveServices, ContainerService, ContainerRegistry, DocumentDB, KeyVault, MachineLearningServices, NetApp, Search, Web, App, Insights, OperationalInsights, Sql, Bing. Poll until Registered or time out.
- RP not registering: confirm the identity has `/register/action` and retry; escalate if it stays Registering past timeout.

### rbac_assign — FR2.1
Assign Discovery built-in roles at RG scope, creating any missing target resource group first (in `workloadRegion`) so the assignment has a scope: Platform Administrator `7a2b6e6c-472e-4b39-8878-a26eb63d75c6` (deploying identity), Platform Contributor `01288891-85ee-45a7-b367-9db3b752fc65`, Platform Reader `3bb7c424-af4e-436b-bfcc-8779c8934c31`, Bookshelf Index Data Reader `8ec773c5-7ce6-4b78-91d1-182f8faa536d`. Platform Administrator principals also get the Azure roles Learn lists for the Discovery administrator, on the same resource groups: Managed Identity Contributor, Managed Identity Operator, Storage Account Contributor, Storage Blob Data Contributor, Network Contributor, AcrPush, plus Reader `acdd72a7-3385-48ef-bd42-f606fba81ae7` at subscription scope. Foundry Owner is assigned by Stage 4 on the workspace managed RG, which doesn't exist yet; Stage 2 reports it as a Skip. Pair project-scoped users with Tools Reader, Chat Model Reader, Storage Container Reader/Contributor; add Storage Blob Data Reader/Contributor on the backing storage scope (container roles do not grant blob access). Platform Administrator cannot assign roles to others.

Human user assignments follow `rbac.humanAccessMode`:

- `permanent-role-assignments`: create standard role assignments.
- `customer-jit-managed`: reuse an active or eligible assignment when available; otherwise create
  time-bound PIM eligibility through `Microsoft.Authorization/roleEligibilityScheduleRequests`
  with `requestType=AdminAssign`. New eligibility uses `rbac.jitEligibilityDurationDays`
  (minimum 7).

Eligible-but-inactive is a successful RBAC result, so Stage 2 continues. The report and
`human-pim-eligibility-<workspace>.md/.json` tell customers which roles to activate. Service
principals and managed identities always receive persistent assignments.

- PIM prerequisites: Microsoft Entra ID P2 or Microsoft Entra ID Governance licensing, plus
  permission to write `Microsoft.Authorization/roleEligibilityScheduleRequests` at every
  requested scope.
- Assignment denied: run as Owner, or Contributor plus User Access Administrator/RBAC Administrator, at subscription scope.
- User assignment denied by JIT policy: select `customer-jit-managed`; do not treat Owner as an override for Azure Policy.

### nsp_perimeter_joiner_role — FR2.1a
Create the one-time-per-subscription custom role with exactly `Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action` and `Microsoft.Network/locations/networkSecurityPerimeterOperationStatuses/read`, and assign it at subscription scope to the Discovery control-plane SP app id `92c174ac-8e41-4815-a1b7-d81b19ab03ce`. Network hardening is on by default, so this must exist before the first workspace/supercomputer/bookshelf deploy.
- Missing role: resource creation fails with NSP association errors; create and assign the role, then retry.

### network_provision — FR2.2-FR2.5 (network.bicep)
Deploy `network.bicep` (one network-RG-scoped deployment) to lay out the VNet, subnets, a shared NSG and route tables. When `network.dnsResourceGroup` is blank or equals the network RG, the same deployment creates the private DNS zones and links. When a distinct centralized DNS RG is configured, Bicep DNS creation is disabled and Stage 2 idempotently creates or reuses every required zone and exact VNet link in that DNS RG. The documented provisioning options are `managed`, `byo` and `byo-spoke`; only `byo-existing` skips this deployment and validates existing networking in Stage 3. All provisioning options use the same template, which declares the VNet address space and subnet collection and can modify an existing VNet; this is not an add-only subnet operation. The managed worksheet offers only `managed`; the BYO worksheet offers `byo`, `byo-spoke` and `byo-existing`. See the [worksheet selection guide](../../scripts/USER-GUIDE.md#3-complete-the-planning-form-choices).

Egress topology is switched separately by `network.outboundType` (`UserDefinedRouting` or `LoadBalancer` in both worksheets). The tool does not create a firewall/NVA, NAT Gateway or hub peering. For UDR, customers must provide a reachable appliance and configure connectivity, forwarding where applicable, firewall rules and SNAT; generating the firewall request does not apply those rules.
- Delegation conflict: ensure the subnet is empty before setting delegation.
- `network.outboundType=UserDefinedRouting` requires `network.nvaNextHop`; otherwise the step fails before deploy.

**FR2.2 VNet/subnets** — each subnet gets its FR1.2 delegation, the shared NSG, and (UDR only) a route table. `private-endpoints` subnet sets `privateEndpointNetworkPolicies=Disabled`.

**FR2.3 NSG allow-list** — shared NSG applied to every subnet: Allow-VNet-In; Allow-AzureLB-In; Allow-PodCIDR-In (source 10.244.0.0/16); Allow-DNS-Out (corp DNS, port 53; `*` when `corpDns` is empty); Allow-AzureCloud-Out 443 and Allow-AzureCloud-KMS-Out 1688 (service-tag egress for Storage/KeyVault/CosmosDB/Search/ACR/ARM/Monitor/AAD); Allow-Internet-Out 443 (required — bootstrap hits CDNs with no service tag); Allow-PodCIDR-Out. NSGs are stateful, so no inbound DNS rule.

**FR2.4 route tables** — `outboundType=UserDefinedRouting`: a spoke route table sends 0.0.0.0/0 and 10.0.0.0/8 to the NVA, and the managedcluster subnet gets its own route table adding `<managedcluster-CIDR> → VnetLocal`. `outboundType=LoadBalancer`: no user route tables (Azure system routes + NSG allow-list govern egress).
- AKS NotReady: confirm the managedcluster subnet CIDR is VnetLocal, not NVA (handled by network.bicep).

**FR2.5 private DNS** — create or reuse the privatelink zones in `network.dnsResourceGroup` (falling back to `network.networkResourceGroup`): cognitiveservices.azure.com, openai.azure.com, services.ai.azure.com, search.windows.net, vaultcore.azure.net, blob/queue/file/table/dfs.core.windows.net, documents.azure.com, azurecr.io. Each is linked to the configured VNet with `registrationEnabled=false`; Stage 2 verifies the exact VNet id rather than accepting any link.
- Zone unlinked: private endpoints resolve to public IPs; re-run the deploy.

### byo_storage — FR2.6
Verify the customer's pre-created BYO storage account (looked up by `storage.accountId`, else by name in the subscription) and fail if it doesn't exist; the tool doesn't create it. Create/verify the containers per the config model, and apply the access model (private endpoint vs service endpoint). Set the Blob CORS rule Discovery Studio needs (origins `https://studio.discovery.microsoft.com`, `https://vscode.dev`, `https://*.vscode-cdn.net`; methods GET, HEAD, DELETE, OPTIONS, PUT; headers `*`; max age 200) with a PUT on `blobServices/default` that keeps the other service properties and unrelated CORS rules. PATCH isn't supported on that resource.
- For `privateEndpoint`, reuse `privatelink.blob.core.windows.net` from
  `network.dnsResourceGroup` (or the network RG), verify its succeeded link to the configured VNet,
  and associate that cross-resource-group zone with the storage endpoint's blob DNS zone group.
  Do not create a duplicate same-name zone in the storage RG. A missing/failed VNet link or zone
  group fails Stage 2.
- Public-access policy deny: see quota_exemption_requests for the Bookshelf MRG storage waiver.

### managed_identity_roles — FR2.1
Assign the UAMI (`managedIdentity.id`) the roles Stage 4 verifies: Platform Contributor, Storage Blob Data Contributor, and AcrPull on the platform RG, and Network Contributor on the VNet (network RG if the VNet isn't found). Runs after network_provision and byo_storage so those scopes exist. Missing `managedIdentity.id` is a Skip; an unresolvable id is a Warn, and Stage 4 then fails its UAMI checks.

### firewall_request_artifact — FR2.7
Emit the network-rule and FQDN allowlist for the customer firewall team using the actual spoke CIDR (a wrong source CIDR caused a repeated deny bootstrap loop). Network rules: DNS 53, Azure PaaS 443, NTP 123/UDP. AKS bootstrap FQDNs (443, plus 80 for the first two): packages.microsoft.com, mcr.microsoft.com, *.data.mcr.microsoft.com, acs-mirror.azureedge.net, management.azure.com, login.microsoftonline.com. Discovery/Foundry PaaS FQDNs: *.cognitiveservices.azure.com, *.openai.azure.com, *.services.ai.azure.com, *.search.windows.net, *.vault.azure.net, *.blob.core.windows.net (and queue/table/file/dfs), *.documents.azure.com, *.azurecr.io, *.azurecontainerapps.io, *.monitor.azure.com, *.windows.net. Emit the specific-port east-west fallback (10250, 443, 53 TCP+UDP, 80; optional 4443 and NodePort range) when any/any is not permitted.
- Repeated `AZFWApplicationRule` deny on packages.microsoft.com: the source CIDR is wrong; regenerate with the real spoke CIDR.

### quota_exemption_requests — FR2.8
Emit quota-increase requests for each FR1.5 shortfall and policy-exemption requests for deny policies with no configuration fix: Cognitive Services public access on the workspace-MRG Foundry account, Log Analytics public access on its MRG, Storage public access on the Bookshelf MRG (time-bound, non-prod first, NSP enforced). NSP association is handled by ordering/retry plus the FR2.1a joiner role, not an exemption. Do not emit a Container Apps allowInsecure request (fixed in the RP).
- `RequestDisallowedByPolicy` at deploy: apply the matching MRG exemption from this bundle.
