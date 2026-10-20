# stage3_validate — Stage 3 validation (consolidated)

Stage 3 · single consolidated PowerShell 7 + Az CLI script · FR mapping: FR3.1–FR3.8
Script: `../../scripts/stage3-validation/stage3_validate.ps1`

## Purpose
One engine that runs the control-plane checks and the optional test-VM harness per service profile, strictly read-only except the ephemeral test VM, and emits JSON plus a human report exiting non-zero on any failure.

## Inputs
- `-ConfigPath <config.json>`, `-Profile supercomputer|workspace|bookshelf`, optional `-WithVm`.

## Behavior
- Select the per-service dependency set for the chosen profile (see dependency_spec).
- Run the control-plane checks (read-only), then optionally the test-VM harness.
- Attach the remediation string to every failed check.
- Emit JSON plus a human report; exit non-zero on any red.

**Current-release limitation:** omit `-WithVm` and arrange independent subnet connectivity
tests. VM creation is blocked by the shared PowerShell wrapper rejecting the empty argument
values used to request no public IP and no additional NSG. VM creation, lifecycle reliability
and probe validation improvements are planned for the next version; the parameter remains
available but is not recommended for this release. Without it, checks are static and do not
prove live subnet egress.
The probe prefers the nodepool subnet; a successful probe there is not system-node subnet evidence.
Missing DNS output may use runner DNS, and missing TCP/HTTPS output is skipped.
Confirm the configured NVA is reachable and obtain successful connectivity evidence from the
required SC subnets before Stage 4; these are customer checks, not enforced script gates.

## Output
- JSON: per-check result with remediation.
- Human: green/red readiness report naming each failing fix.

## Exit codes
- 0 = all checks green.
- Non-zero = at least one failure (see report).

## Folded checks
Each check ran as a separate sub-script before consolidation; the logic now lives in `stage3_validate.ps1`. It reads the profile dependency set from `../../scripts/stage3-validation/dependency-spec.json`.

### dependency_spec — FR3.8
Load the dev-owned per-service dependency spec that drives which checks run per profile (subnets, delegations, DNS zones, PEs, routes, FQDNs). Fail closed if the spec version is older than the deployed platform.
- Stale spec: update the dependency spec in the feature PR that changed the dependency.

### check_subnet_delegation — FR3.6a
Read each Discovery subnet and compare its delegation to the FR1.2 requirement (read-only).
- Wrong delegation: set the required delegation (Stage 2 network_provision).

### check_nsg_effective — FR3.6b
Use `az network nic list-effective-nsg` to confirm the effective rules include the FR2.3 set, especially Allow-Internet-Out 443 and the east-west path (read-only). Before a NIC exists, check the subnet NSG rules. A subnet with no NSG passes, because the Azure defaults allow both paths.
- Missing rule: add it in Stage 2 nsg_rules (or your own NSG for byo-existing) and re-validate.

### check_effective_routes — FR3.6c
Use `az network nic show-effective-route-table` and `az network watcher show-next-hop` where a NIC/VM is available; otherwise inspect the subnet route table. In UDR mode, the managedcluster check verifies VnetLocal for its own CIDR and other subnet checks verify the default route points to the configured NVA. In LoadBalancer mode, checks allow system routing without those UDRs. These checks do not prove NVA reachability or working Internet egress.
- Managedcluster local traffic via NVA: restore VnetLocal for its own CIDR; do not remove its required UDR Internet egress route.

### check_dns_and_pe — FR3.6d
Confirm each FR2.5 privatelink zone exists and is linked, and private endpoints are Approved with non-empty DNS (Bookshelf expects 3 PEs approved; the Foundry endpoint carries 2 zones) — read-only.
- Zone unlinked or PE not Approved: fix the link / approve the PE (Stage 2 private_dns; Stage 4 PE approval). For byo-existing the customer owns the zones; the remediation prints the `az network private-dns zone create` and `link vnet create` commands.

### check_quota — FR3.6e
Re-run the Stage 1 quota checks (shared `Get-VcpuQuotaResult` / `Get-ModelQuotaResult` in `lib/OnboardingCommon.psm1`) as a blocking gate. The supercomputer profile emits `vcpu-quota`; the workspace profile emits `model-quota` (gpt-5.4 GlobalStandard, 450K TPM). Skipped when the target supercomputer or workspace already exists and is Succeeded. Waivable with the same check id.
- TPM shortfall: delete unused gpt-5.4 deployments, purge soft-deleted Foundry accounts, or request more quota.
- vCPU shortfall: request a regional/family quota increase.
### testvm_lifecycle — FR3.7, FR3.7g
With `-WithVm`, provision a disposable VM in the target subnet (preferring nodepool; no public IP or NSG override, generated SSH keys), run the inline connectivity script via `az vm run-command invoke RunShellScript`, then attempt to delete the VM, NIC, and disk on exit. Check cleanup results/resources after failures; deletion is not guaranteed.
- VM create fails on SKU: pick a region-allowed SKU (see quota_sku).
- Leftover resources: inspect the reported VM/NIC/disk IDs and clean up approved probe resources.

The test VM runs the following probes (results parsed by the consolidated script):

- probe_dns — FR3.7a: `getent hosts` must return an IP for mcr.microsoft.com, packages.aks.azure.com, packages.microsoft.com, management.azure.com, login.microsoftonline.com, <region>.data.mcr.microsoft.com. Missing IP = FAIL → fix VNet DNS / private DNS zone links.
- probe_tcp443 — FR3.7b: test `/dev/tcp/$h/443` for each host; expect 443 OPEN. 443 BLOCKED with DNS ok → NSG denies egress or a UDR black-holes the route.
- probe_https — FR3.7c: expected status codes mcr.microsoft.com/v2/ → 200, packages.aks.azure.com/ → 400, management.azure.com/ → 400/401, login.microsoftonline.com/ → 200. TCP open but HTTPS fails → NVA allowlist incomplete or TLS-inspecting.
- probe_artifacts — FR3.7d: pull packages-microsoft-prod.deb, the kubelet node bundle (ranged GET), and the Ubuntu mirror Release (HTTP 200). Fails while TCP open → NVA allowlist incomplete or TLS-inspecting.
- probe_pe_resolution — FR3.7e: resolve each privatelink.* FQDN and assert a private IP. Public IP → fix private DNS zone links / VNet DNS.
- probe_eastwest — FR3.7f: test TCP 10250 from the managed cluster subnet to the node subnets. Handshake timeout → allow east-west 10250 (symmetric routing or an explicit rule).
