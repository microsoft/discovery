# stage2_prepare — Stage 2 landing zone (consolidated)

Stage 2 · single consolidated PowerShell 7 + Az CLI script · FR mapping: FR2.1–FR2.9
Script: `../../scripts/stage2-landing-zone/stage2_prepare.ps1`

## Purpose
Turn the signed config into a deployed landing zone idempotently: identity, network, storage, private DNS, quota/exemption requests, and the firewall artifact.

## Inputs
- `--config <config.json>` from Stage 1.
- `--subscription` / `--resource-group` targets.

## Behavior
- Run the folded steps in dependency order: RP register → RBAC → NSP joiner role → network → NSG → routes → DNS → storage → artifacts.
- Converge on re-run without duplicate or conflicting resources (FR2.9).
- Stop and surface the first hard failure with its remediation.

## Output
- JSON: per-step resource plus provisioning state.
- Human: landing-zone build log and the generated request artifacts.

## Exit codes
- 0 = all steps green.
- Non-zero = at least one failure (see report).

## Folded steps
Each step ran as a separate sub-script before consolidation; the logic now lives in `stage2_prepare.ps1`. Only this stage and Stage 4 write platform resources.

### rp_register — FR2.1
Run `az provider register --namespace Microsoft.Discovery`, then verify each dependent RP reaches Registered: Microsoft.Network, Compute, Storage, ManagedIdentity, Authorization, CognitiveServices, ContainerService, ContainerRegistry, DocumentDB, KeyVault, MachineLearningServices, NetApp, Search, Web, App, Insights, OperationalInsights, Sql, Bing. Poll until Registered or time out.
- RP not registering: confirm the identity has `/register/action` and retry; escalate if it stays Registering past timeout.

### rbac_assign — FR2.1
Assign Discovery built-in roles at RG scope: Platform Administrator `7a2b6e6c-472e-4b39-8878-a26eb63d75c6` (deploying identity), Platform Contributor `01288891-85ee-45a7-b367-9db3b752fc65`, Platform Reader `3bb7c424-af4e-436b-bfcc-8779c8934c31`, Bookshelf Index Data Reader `8ec773c5-7ce6-4b78-91d1-182f8faa536d`. Pair project-scoped users with Tools Reader, Chat Model Reader, Storage Container Reader/Contributor; add Storage Blob Data Reader/Contributor on the backing storage scope (container roles do not grant blob access). Platform Administrator cannot assign roles to others.
- Assignment denied: run as Owner/User Access Administrator/RBAC Administrator at the scope.

### nsp_perimeter_joiner_role — FR2.1a
Create the one-time-per-subscription custom role with exactly `Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action` and `Microsoft.Network/locations/networkSecurityPerimeterOperationStatuses/read`, and assign it at subscription scope to the Discovery control-plane SP app id `92c174ac-8e41-4815-a1b7-d81b19ab03ce`. Network hardening is on by default, so this must exist before the first workspace/supercomputer/bookshelf deploy.
- Missing role: resource creation fails with NSP association errors; create and assign the role, then retry.

### network_provision — FR2.2-FR2.5 (network.bicep)
Deploy `network.bicep` (one RG-scoped deployment) to lay out the VNet, subnets, a shared NSG, route tables and private DNS zones declaratively. Runs only when `network.model` is a build model (`byo`/`byo-spoke`/`greenfield`); `byo-existing` and `managed` skip provisioning (validate in Stage 3 / RP-managed). Egress topology is switched by `network.outboundType`.
- Delegation conflict: ensure the subnet is empty before setting delegation.
- `network.outboundType=UserDefinedRouting` requires `network.nvaNextHop`; otherwise the step fails before deploy.

**FR2.2 VNet/subnets** — each subnet gets its FR1.2 delegation, the shared NSG, and (UDR only) a route table. `private-endpoints` subnet sets `privateEndpointNetworkPolicies=Disabled`.

**FR2.3 NSG allow-list** — shared NSG applied to every subnet: Allow-VNet-In; Allow-AzureLB-In; Allow-PodCIDR-In (source 10.244.0.0/16); Allow-DNS-Out (corp DNS, port 53; `*` when `corpDns` is empty); Allow-AzureCloud-Out 443 and Allow-AzureCloud-KMS-Out 1688 (service-tag egress for Storage/KeyVault/CosmosDB/Search/ACR/ARM/Monitor/AAD); Allow-Internet-Out 443 (required — bootstrap hits CDNs with no service tag); Allow-PodCIDR-Out. NSGs are stateful, so no inbound DNS rule.

**FR2.4 route tables** — `outboundType=UserDefinedRouting`: a spoke route table sends 0.0.0.0/0 and 10.0.0.0/8 to the NVA, and the managedcluster subnet gets its own route table adding `<managedcluster-CIDR> → VnetLocal`. `outboundType=LoadBalancer`: no user route tables (Azure system routes + NSG allow-list govern egress).
- AKS NotReady: confirm the managedcluster subnet CIDR is VnetLocal, not NVA (handled by network.bicep).

**FR2.5 private DNS** — create and link the privatelink zones: cognitiveservices.azure.com, openai.azure.com, services.ai.azure.com, search.windows.net, vaultcore.azure.net, blob/queue/file/table/dfs.core.windows.net, documents.azure.com, azurecr.io. Each is VNet-linked (registrationEnabled=false).
- Zone unlinked: private endpoints resolve to public IPs; re-run the deploy.

### byo_storage — FR2.6
Create/verify the BYO storage account and containers per the config model, and apply the access model (private endpoint vs service endpoint).
- Public-access policy deny: see quota_exemption_requests for the Bookshelf MRG storage waiver.

### firewall_request_artifact — FR2.7
Emit the network-rule and FQDN allowlist for the customer firewall team using the actual spoke CIDR (a wrong source CIDR caused a repeated deny bootstrap loop). Network rules: DNS 53, Azure PaaS 443, NTP 123/UDP. AKS bootstrap FQDNs (443, plus 80 for the first two): packages.microsoft.com, mcr.microsoft.com, *.data.mcr.microsoft.com, acs-mirror.azureedge.net, management.azure.com, login.microsoftonline.com. Discovery/Foundry PaaS FQDNs: *.cognitiveservices.azure.com, *.openai.azure.com, *.services.ai.azure.com, *.search.windows.net, *.vault.azure.net, *.blob.core.windows.net (and queue/table/file/dfs), *.documents.azure.com, *.azurecr.io, *.azurecontainerapps.io, *.monitor.azure.com, *.windows.net. Emit the specific-port east-west fallback (10250, 443, 53 TCP+UDP, 80; optional 4443 and NodePort range) when any/any is not permitted.
- Repeated `AZFWApplicationRule` deny on packages.microsoft.com: the source CIDR is wrong; regenerate with the real spoke CIDR.

### quota_exemption_requests — FR2.8
Emit quota-increase requests for each FR1.5 shortfall and policy-exemption requests for deny policies with no configuration fix: Cognitive Services public access on the workspace-MRG Foundry account, Log Analytics public access on its MRG, Storage public access on the Bookshelf MRG (time-bound, non-prod first, NSP enforced). NSP association is handled by ordering/retry plus the FR2.1a joiner role, not an exemption. Do not emit a Container Apps allowInsecure request (fixed in the RP).
- `RequestDisallowedByPolicy` at deploy: apply the matching MRG exemption from this bundle.
