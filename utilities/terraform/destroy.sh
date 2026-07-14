#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# destroy.sh
#
# Tear down everything created by the Terraform utility, including the two
# managed resource groups (MRGs) that Discovery spins up but does not always
# clean up on its own:
#
#   * The Workspace MRG (owned by Microsoft.Discovery/workspaces).
#   * The Supercomputer MRG (owned by Microsoft.Discovery/supercomputers;
#     hosts the underlying AKS cluster and often needs a second delete pass).
#
# The script is idempotent and safe to re-run. It:
#
#   1. Discovers Discovery workspace(s) and supercomputer(s) in the target RG
#      and records their managedResourceGroupId values BEFORE anything is
#      deleted (the MRG pointer disappears once the parent resource is gone).
#   2. Optionally runs `terraform destroy` if a local .terraform state is
#      present and --skip-terraform was not passed.
#   3. Pre-drains Discovery children (projects, chat models, storage
#      containers, node pools, then workspaces and supercomputers) ONE AT A
#      TIME. This prevents the parallel-cascade race that produces
#      InvalidResourceOperation and ServerTimeout / stuck-SAL deadlocks.
#   4. Detaches AKS-orphaned NSGs from any subnets in the RG's VNets. When
#      Discovery's Supercomputer AKS attaches auto-generated NSGs to your
#      BYO subnets, deleting the SC does NOT remove those references -- the
#      subnet then blocks its own deletion with 409
#      InUseNetworkSecurityGroupCannotBeDeleted and stalls the RG cascade.
#   4b. Detects orphaned serviceAssociationLinks (e.g. 'legionservicelink'
#       installed by the AI Foundry / AML agent service on the delegated
#       agentSubnet). These CANNOT be removed via any self-service API --
#       only the owning first-party service is authorized. Confirmed by
#       Microsoft Q&A #12746700 and #12722985. If detected, the script
#       stops with a support-ticket template OR (if --abandon-orphan-vnet
#       is set) tags the RG as quarantined and skips the doomed RG delete.
#   5. Deletes the primary RG and polls for completion.
#   6. Force-deletes any MRGs that survived, retrying the Supercomputer MRG
#      up to 3 times because its AKS-backed cleanup is racy.
#
# Usage:
#   ./destroy.sh                                 # defaults: rg-discovery-terraform, prompts
#   ./destroy.sh -g my-rg                        # different resource group
#   ./destroy.sh --skip-terraform                # skip `terraform destroy`
#   ./destroy.sh --dry-run                       # print plan, delete nothing
#   ./destroy.sh -y                              # non-interactive (no prompt)
#   ./destroy.sh --timeout 180                   # max minutes to wait on primary RG (default 120)
#   ./destroy.sh --poll-interval 30              # seconds between progress polls (default 60)
#   ./destroy.sh --abandon-orphan-vnet           # tag+keep RG if an orphaned SAL blocks VNet delete
#
# Progress: the script submits the RG delete asynchronously and polls itself
# every minute, printing remaining resource count and elapsed time. Every 5
# minutes it also scans the activity log for REAL delete failures (filtering
# out the ResourceGroupBeingDeleted 409 noise that Discovery's control plane
# generates while the RG is deprovisioning). If nothing has moved for 15
# minutes it surfaces a diagnostic block with next-step commands.
#
# Requirements: az CLI, jq, an active `az login` session pointed at the
# subscription that owns the RG.
# -----------------------------------------------------------------------------

set -euo pipefail

# ---- defaults ---------------------------------------------------------------

RESOURCE_GROUP="rg-discovery-terraform"
SKIP_TERRAFORM=false
DRY_RUN=false
ASSUME_YES=false
ABANDON_ORPHAN_VNET=false   # when true, tag+keep RG if VNet delete is blocked by an orphan SAL
MRG_RETRIES=3
MRG_RETRY_DELAY=30

# Progress monitoring for the primary-RG delete phase.
POLL_INTERVAL=60         # seconds between resource-count polls
STALL_WARN_MINUTES=15    # warn if the resource count has not decreased for this long
RG_DELETE_TIMEOUT=120    # give up on the primary RG delete after this many minutes
ACTIVITY_LOG_EVERY=5     # minutes between activity-log failure scans

# ---- pretty output ----------------------------------------------------------

if [[ -t 1 ]]; then
  C_INFO=$'\033[36m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OK=$'\033[32m'; C_OFF=$'\033[0m'
else
  C_INFO=""; C_WARN=""; C_ERR=""; C_OK=""; C_OFF=""
fi

log()  { printf "%s[destroy]%s %s\n" "$C_INFO" "$C_OFF" "$*"; }
warn() { printf "%s[destroy]%s %s\n" "$C_WARN" "$C_OFF" "$*"; }
err()  { printf "%s[destroy]%s %s\n" "$C_ERR"  "$C_OFF" "$*" >&2; }
ok()   { printf "%s[destroy]%s %s\n" "$C_OK"   "$C_OFF" "$*"; }

usage() {
  sed -n '3,50p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# ---- arg parsing ------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    -g|--resource-group)   RESOURCE_GROUP="$2"; shift 2 ;;
    --skip-terraform)      SKIP_TERRAFORM=true; shift ;;
    --dry-run)             DRY_RUN=true; shift ;;
    -y|--yes)              ASSUME_YES=true; shift ;;
    --timeout)             RG_DELETE_TIMEOUT="$2"; shift 2 ;;
    --poll-interval)       POLL_INTERVAL="$2"; shift 2 ;;
    --abandon-orphan-vnet) ABANDON_ORPHAN_VNET=true; shift ;;
    -h|--help)             usage 0 ;;
    *)                   err "unknown argument: $1"; usage 1 ;;
  esac
done

# ---- preflight --------------------------------------------------------------

command -v az >/dev/null || { err "az CLI not found on PATH"; exit 1; }
command -v jq >/dev/null || { err "jq not found on PATH"; exit 1; }

if ! az account show >/dev/null 2>&1; then
  err "not signed in. Run: az login"
  exit 1
fi

SUB_ID=$(az account show --query id -o tsv)
SUB_NAME=$(az account show --query name -o tsv)

log "subscription: ${SUB_NAME} (${SUB_ID})"
log "target RG:    ${RESOURCE_GROUP}"

if ! az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
  warn "resource group '${RESOURCE_GROUP}' does not exist -- nothing to do for the primary RG"
  RG_EXISTS=false
else
  RG_EXISTS=true
fi

# ---- discover MRGs BEFORE anything is deleted -------------------------------
#
# managedResourceGroupId is an ARM resource ID like
#   /subscriptions/<sub>/resourceGroups/<mrg-name>
# We collect the RG names (last segment) into MRGS[].

MRGS=()

collect_mrgs_for_type() {
  local rp_type="$1"     # e.g. Microsoft.Discovery/workspaces
  local api_version="$2" # e.g. 2026-06-01

  if ! $RG_EXISTS; then return 0; fi

  local ids
  ids=$(az resource list \
          --resource-group "$RESOURCE_GROUP" \
          --resource-type "$rp_type" \
          --query "[].id" -o tsv 2>/dev/null || true)

  [[ -z "$ids" ]] && return 0

  while IFS= read -r rid; do
    [[ -z "$rid" ]] && continue
    local resource_name="${rid##*/}"
    local mrg_id
    mrg_id=$(az rest --method GET \
                --url "https://management.azure.com${rid}?api-version=${api_version}" \
                --query "properties.managedResourceGroupId" -o tsv 2>/dev/null || true)
    if [[ -n "$mrg_id" && "$mrg_id" != "null" ]]; then
      local mrg_name="${mrg_id##*/}"
      MRGS+=("$mrg_name")
      log "  discovered MRG for ${rp_type##*/} '${resource_name}': ${mrg_name} (via managedResourceGroupId)"
    else
      # Fallback: for Failed workspaces/SCs the RP nulls out
      # managedResourceGroupId. The MRG still exists in the subscription
      # under the convention 'mrg-dwsp-<resource-name>-<suffix>' (workspaces)
      # or a similar prefix for supercomputers. Scan the subscription for
      # any RG whose name contains the resource name and starts with 'mrg-'.
      local mrg_matches
      mrg_matches=$(az group list \
        --query "[?starts_with(name, 'mrg-') && contains(name, '${resource_name}')].name" \
        -o tsv 2>/dev/null || true)
      while IFS= read -r mrg_name; do
        [[ -z "$mrg_name" ]] && continue
        MRGS+=("$mrg_name")
        log "  discovered MRG for ${rp_type##*/} '${resource_name}': ${mrg_name} (via name-pattern fallback; parent state likely Failed)"
      done <<< "$mrg_matches"
    fi
  done <<< "$ids"
}

log "discovering managed resource groups..."
collect_mrgs_for_type "Microsoft.Discovery/workspaces"      "2026-06-01"
collect_mrgs_for_type "Microsoft.Discovery/supercomputers"  "2026-06-01"

# de-duplicate
if [[ ${#MRGS[@]} -gt 0 ]]; then
  # shellcheck disable=SC2207
  MRGS=($(printf "%s\n" "${MRGS[@]}" | awk '!seen[$0]++'))
fi

if [[ ${#MRGS[@]} -eq 0 ]]; then
  warn "no managed resource groups discovered (either none exist yet, or the parent resources are already gone)"
fi

# ---- plan summary + confirmation --------------------------------------------

echo
log "plan:"
$SKIP_TERRAFORM || [[ ! -d ".terraform" ]] \
  && log "  step 1:   skip 'terraform destroy' (no .terraform dir or --skip-terraform set)" \
  || log "  step 1:   run 'terraform destroy -auto-approve'"
$RG_EXISTS \
  && log "  step 1.5: pre-drain Discovery workspaces/supercomputers serially" \
  || log "  step 1.5: (skip) RG '${RESOURCE_GROUP}' does not exist"
$RG_EXISTS \
  && log "  step 1.6: detach AKS-orphaned NSGs from BYO subnets" \
  || log "  step 1.6: (skip) RG '${RESOURCE_GROUP}' does not exist"
$RG_EXISTS \
  && log "  step 1.7: detect orphaned serviceAssociationLinks (legionservicelink)" \
  || log "  step 1.7: (skip) RG '${RESOURCE_GROUP}' does not exist"
$RG_EXISTS \
  && log "  step 2:   delete resource group '${RESOURCE_GROUP}'" \
  || log "  step 2:   (skip) RG '${RESOURCE_GROUP}' does not exist"
if [[ ${#MRGS[@]} -gt 0 ]]; then
  log "  step 3:   force-delete managed resource groups (SC MRG retried up to ${MRG_RETRIES}x):"
  for m in "${MRGS[@]}"; do log "              - ${m}"; done
else
  log "  step 3:   (skip) no MRGs to clean up"
fi
echo

if $DRY_RUN; then
  ok "dry-run complete. No changes made."
  exit 0
fi

if ! $ASSUME_YES; then
  read -r -p "Proceed with destruction? Type the RG name '${RESOURCE_GROUP}' to confirm: " confirm
  if [[ "$confirm" != "$RESOURCE_GROUP" ]]; then
    err "confirmation did not match. Aborting."
    exit 1
  fi
fi

# ---- step 1: terraform destroy ----------------------------------------------

if ! $SKIP_TERRAFORM && [[ -d ".terraform" ]]; then
  log "step 1: running 'terraform destroy -auto-approve'..."
  if terraform destroy -auto-approve; then
    ok "terraform destroy completed"
  else
    warn "terraform destroy exited non-zero -- continuing with imperative cleanup"
  fi
else
  log "step 1: skipped"
fi

# ---- step 1.5: pre-drain Discovery resources serially ----------------------
#
# The RG-delete cascade fans out to every child in parallel, which produces
# two well-known Discovery failure modes:
#
#   * InvalidResourceOperation ("another DELETE ... is active/in-progress")
#     on workspaces/nodepools when the cascade races itself.
#   * Workspaces_Delete ServerTimeout that leaves a serviceAssociationLink
#     ('legionservicelink') on the delegated agentSubnet, which then pins
#     the subnet, which pins every NSG in the VNet.
#
# The fix is to delete workspaces and supercomputers ONE AT A TIME, with a
# long per-resource timeout, and wait for each to actually be gone before
# starting the next. Only then do we let the RG cascade take the rest.
#
# If a delete is already in flight (from a previous script run or the RG
# cascade), we don't submit another one -- we just poll for the resource
# to disappear.

wait_for_resource_gone() {
  local resource_id="$1"
  local timeout_min="$2"
  local name="${resource_id##*/}"
  local start_ts=$(date +%s)

  while az resource show --ids "$resource_id" >/dev/null 2>&1; do
    local now_ts=$(date +%s)
    local elapsed_min=$(( (now_ts - start_ts) / 60 ))
    if (( elapsed_min >= timeout_min )); then
      err "  timed out waiting for '${name}' to delete after ${timeout_min}m"
      return 1
    fi
    log "  [${elapsed_min}m] waiting for '${name}' to finish deleting..."
    sleep 60
  done
  ok "  '${name}' is gone"
  return 0
}

predrain_type() {
  local rp_type="$1"     # e.g. Microsoft.Discovery/workspaces
  local timeout_min="$2"

  local ids
  ids=$(az resource list -g "$RESOURCE_GROUP" --resource-type "$rp_type" \
          --query "[].id" -o tsv 2>/dev/null || true)
  [[ -z "$ids" ]] && return 0

  while IFS= read -r rid; do
    [[ -z "$rid" ]] && continue
    local name="${rid##*/}"
    local state
    state=$(az resource show --ids "$rid" --query "properties.provisioningState" -o tsv 2>/dev/null || echo "unknown")

    if [[ "$state" == "Deleting" ]]; then
      log "  '${name}' is already Deleting -- attaching to in-flight op"
    else
      log "  submitting delete for '${name}' (state=${state})"
      # --no-wait so we can poll and report. 409 (already deleting) is fine.
      az resource delete --ids "$rid" --no-wait 2>/dev/null || true
    fi

    wait_for_resource_gone "$rid" "$timeout_min" || return 1
  done <<< "$ids"
}

if az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
  log "step 1.5: pre-draining Discovery resources serially (per-resource timeout 90m)..."
  # Order matters: children first, then parents.
  #   projects, chat model deployments, storage containers -> workspace children
  #   nodepools -> supercomputer children
  #   workspaces, supercomputers -> top-level
  predrain_type "Microsoft.Discovery/workspaces/projects"             30
  predrain_type "Microsoft.Discovery/workspaces/chatModelDeployments" 30
  predrain_type "Microsoft.Discovery/storageContainers"               30
  predrain_type "Microsoft.Discovery/supercomputers/nodePools"        60
  predrain_type "Microsoft.Discovery/workspaces"                      90
  predrain_type "Microsoft.Discovery/supercomputers"                  90
  ok "step 1.5: Discovery pre-drain complete"
else
  log "step 1.5: RG already gone, skipping pre-drain"
fi

# ---- step 1.6: detach AKS-orphaned NSGs from BYO subnets -------------------
#
# Discovery's Supercomputer stands up an AKS cluster that attaches
# auto-generated NSGs (named <vnet>-<subnet>-nsg-<region>) to the customer's
# BYO subnets. When the SC is deleted, the AKS resources go away but the NSG
# references on the subnets are NOT cleaned up. The next `az group delete`
# then stalls indefinitely on 409 InUseNetworkSecurityGroupCannotBeDeleted
# because the subnet won't delete while it references the NSG, and the NSG
# won't delete while a subnet references it.
#
# This step walks every VNet in the RG, detaches any NSG from every subnet
# (regardless of whether Terraform or AKS created it), and lets the RG
# cascade handle the NSG deletion afterward. Idempotent -- if nothing is
# attached, nothing happens.
detach_orphaned_nsgs() {
  local vnets
  vnets=$(az network vnet list -g "$RESOURCE_GROUP" --query "[].name" -o tsv 2>/dev/null || true)
  if [[ -z "$vnets" ]]; then
    log "  step 1.6: no VNets in RG, nothing to detach"
    return 0
  fi

  local detached=0
  while IFS= read -r vnet; do
    [[ -z "$vnet" ]] && continue
    local subnets
    subnets=$(az network vnet subnet list -g "$RESOURCE_GROUP" --vnet-name "$vnet" \
      --query "[?networkSecurityGroup!=null].name" -o tsv 2>/dev/null || true)
    while IFS= read -r subnet; do
      [[ -z "$subnet" ]] && continue
      log "  step 1.6: detaching NSG from ${vnet}/${subnet}"
      if [[ "$DRY_RUN" == "true" ]]; then
        log "    [dry-run] az network vnet subnet update -g $RESOURCE_GROUP --vnet-name $vnet -n $subnet --remove networkSecurityGroup"
      else
        az network vnet subnet update -g "$RESOURCE_GROUP" --vnet-name "$vnet" \
          -n "$subnet" --remove networkSecurityGroup >/dev/null 2>&1 \
          || warn "    failed to detach NSG from ${vnet}/${subnet} -- continuing"
      fi
      detached=$((detached + 1))
    done <<< "$subnets"
  done <<< "$vnets"

  if [[ $detached -eq 0 ]]; then
    log "  step 1.6: no subnets had NSGs attached"
  else
    ok "  step 1.6: detached ${detached} NSG reference(s)"
  fi
}

if az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
  log "step 1.6: detaching AKS-orphaned NSGs from BYO subnets..."
  detach_orphaned_nsgs
else
  log "step 1.6: RG already gone, skipping NSG detach"
fi

# ---- step 1.7: detect orphaned subnet serviceAssociationLinks --------------
#
# Background: Discovery workspaces install an AI Foundry / AML capability host
# that adds a serviceAssociationLink (SAL) named 'legionservicelink' on the
# delegated agentSubnet. When the workspace deletes cleanly, the capability
# host removes its own SAL. When a prior destroy attempt force-deleted the
# workspace's managed RG (mrg-dwsp-*) before the capability host could
# deregister -- or the workspace-delete API call timed out -- the SAL is
# stranded on the subnet as an ORPHAN.
#
# CRITICAL: there is NO self-service API to remove an orphaned
# 'Microsoft.App/environments' SAL. The Network RP allows the SAL to be
# deleted only by the owning first-party service (the capability host, which
# no longer exists). Confirmed unauthorized as of 2026-07:
#
#   * `az network vnet subnet update --remove serviceAssociationLinks` -> UnauthorizedClientApplication
#   * `az rest DELETE .../serviceAssociationLinks/legionservicelink` -> UnauthorizedClientApplication
#   * `az rest PATCH subnet {serviceAssociationLinks: []}` -> UnauthorizedClientApplication
#   * `Microsoft.Web/purgeUnusedVirtualNetworkIntegration` -> returns success but does NOT remove Microsoft.App/environments SALs
#
# Cited by Microsoft Q&A #12746700 and #12722985: the only fix is a Microsoft
# Support ticket for backend cleanup, or -- pragmatically -- ABANDON the RG.
# See also: https://aka.ms/deletesubnet
#
# What this step does:
#   1. Enumerate every subnet in the RG and detect orphaned SALs.
#   2. If none found, log and continue.
#   3. If found, PRINT a support-ticket template and stop the destroy unless
#      --abandon-orphan-vnet was passed. In abandon mode, tag the RG so it's
#      obviously quarantined and let step 2 skip the RG delete.

ORPHAN_SAL_DETECTED=false
ORPHAN_SAL_SUBNETS=()   # each entry: "<vnet>/<subnet>=<sal1>,<sal2>"

detect_orphaned_sals() {
  local vnets
  vnets=$(az network vnet list -g "$RESOURCE_GROUP" --query "[].name" -o tsv 2>/dev/null || true)
  if [[ -z "$vnets" ]]; then
    log "  step 1.7: no VNets in RG"
    return 0
  fi

  while IFS= read -r vnet; do
    [[ -z "$vnet" ]] && continue
    local subnets_json
    subnets_json=$(az network vnet subnet list -g "$RESOURCE_GROUP" --vnet-name "$vnet" \
      --query "[?serviceAssociationLinks!=null && length(serviceAssociationLinks)>\`0\`].{name:name, sals:serviceAssociationLinks[].name}" \
      -o json 2>/dev/null || echo "[]")
    local count
    count=$(echo "$subnets_json" | jq 'length')
    [[ "$count" == "0" ]] && continue

    ORPHAN_SAL_DETECTED=true
    while IFS= read -r entry; do
      local subnet sals
      subnet=$(echo "$entry" | jq -r '.name')
      sals=$(echo "$entry" | jq -r '.sals | join(",")')
      ORPHAN_SAL_SUBNETS+=("${vnet}/${subnet}=${sals}")
      warn "  step 1.7: ORPHAN SAL detected: ${vnet}/${subnet} -> ${sals}"
    done < <(echo "$subnets_json" | jq -c '.[]')
  done <<< "$vnets"
}

print_orphan_sal_guidance() {
  err ""
  err "  ============================================================================"
  err "  ORPHANED serviceAssociationLink DETECTED - NO SELF-SERVICE FIX AVAILABLE"
  err "  ============================================================================"
  err ""
  err "  Affected subnet(s):"
  for entry in "${ORPHAN_SAL_SUBNETS[@]}"; do
    err "    * ${entry}"
  done
  err ""
  err "  Why this happens: a Discovery workspace's AI Foundry capability host"
  err "  installs a SAL on the delegated agentSubnet. If the workspace or its"
  err "  managed resource group is force-deleted before the capability host can"
  err "  deregister, the SAL becomes an orphan. The Network RP blocks SAL removal"
  err "  by any non-owning client (Azure CLI, PowerShell, Terraform, portal), so"
  err "  no local fix works. This is documented in Microsoft Q&A #12746700 and"
  err "  #12722985; see also https://aka.ms/deletesubnet."
  err ""
  err "  Two paths forward:"
  err ""
  err "  A. RECOMMENDED: Abandon this RG and redeploy to a fresh one."
  err "     1. Re-run this script with --abandon-orphan-vnet to tag the RG and"
  err "        skip the failing VNet/RG delete:"
  err "          ./destroy.sh -g ${RESOURCE_GROUP} --abandon-orphan-vnet -y"
  err "     2. Update terraform.tfvars to point at a NEW resource group name."
  err "     3. Create the new RG and re-run 'terraform apply'."
  err "     4. (Optional) File a Microsoft Support ticket to purge the orphaned"
  err "        SAL(s) so the tainted RG can eventually be cleaned up."
  err ""
  err "  B. WAIT-AND-RETRY: File a Microsoft Support ticket now, wait for backend"
  err "     cleanup, then re-run this script. Support-ticket template:"
  err ""
  err "     Subject: Orphaned Microsoft.App/environments serviceAssociationLink"
  err "              (legionservicelink) blocking subnet + VNet deletion"
  err ""
  err "     Subscription: ${SUB_ID}"
  err "     Resource group: ${RESOURCE_GROUP}"
  err "     Affected subnet resource IDs:"
  for entry in "${ORPHAN_SAL_SUBNETS[@]}"; do
    local pair="${entry%=*}"
    local vnet="${pair%%/*}"
    local subnet="${pair##*/}"
    err "       /subscriptions/${SUB_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Network/virtualNetworks/${vnet}/subnets/${subnet}"
  done
  err ""
  err "     Please have the Networking backend team remove the orphaned"
  err "     'legionservicelink' serviceAssociationLink(s) so subnet + VNet"
  err "     deletion can proceed. The owning capability host has already been"
  err "     deleted (linked resource no longer exists)."
  err ""
  err "  ============================================================================"
  err ""
}

if az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
  log "step 1.7: scanning for orphaned subnet serviceAssociationLinks..."
  detect_orphaned_sals
  if $ORPHAN_SAL_DETECTED; then
    if $ABANDON_ORPHAN_VNET; then
      warn "  --abandon-orphan-vnet set: tagging RG and skipping the failing VNet/RG delete"
      if ! $DRY_RUN; then
        az group update -n "$RESOURCE_GROUP" --set \
          tags.discovery_status=orphaned \
          tags.discovery_reason=legionservicelink_orphan \
          tags.discovery_orphan_date="$(date -u +%Y-%m-%d)" \
          tags.discovery_support_ticket=pending \
          -o none 2>/dev/null \
          || warn "  failed to tag RG -- continuing"
      fi
      # Skip the RG-delete phase; anything else in the RG has already been
      # drained by steps 1.5/1.6. The MRG cleanup in step 3 still runs.
      SKIP_RG_DELETE=true
    else
      print_orphan_sal_guidance
      exit 2
    fi
  else
    ok "  step 1.7: no orphaned serviceAssociationLinks found"
  fi
else
  log "step 1.7: RG already gone, skipping SAL scan"
fi

SKIP_RG_DELETE="${SKIP_RG_DELETE:-false}"

# ---- step 2: delete the primary RG (with live progress monitoring) ---------
#
# We deliberately use --no-wait and poll ourselves so we can:
#   * show resource count / elapsed time each minute
#   * surface REAL delete failures (not the ResourceGroupBeingDeleted 409
#     noise from Discovery's control plane reconciling in the background)
#   * warn if no progress has been made for STALL_WARN_MINUTES
#   * time out cleanly with next-step commands instead of blocking forever

count_rg_resources() {
  az resource list -g "$RESOURCE_GROUP" --query "length(@)" -o tsv 2>/dev/null || echo -1
}

# Distinguish REAL failures from Discovery's benign reconciliation noise.
# The noise pattern: NodePools_Update / Workspaces_Update / Supercomputers_Update
# receiving a 409 whose message contains 'ResourceGroupBeingDeleted'. Every
# other Failed op -- including the important ones we care about like
# InUseNetworkSecurityGroupCannotBeDeleted and InvalidResourceOperation ("another
# DELETE in progress") -- must be surfaced.
scan_real_failures() {
  local since_min="$1"
  az monitor activity-log list -g "$RESOURCE_GROUP" --offset "${since_min}m" \
    --query "[?status.value=='Failed' && !(contains(operationName.value,'_Update') && contains(to_string(properties.statusMessage),'ResourceGroupBeingDeleted'))].{time:eventTimestamp, op:operationName.localizedValue, code:properties.statusCode, msg:properties.statusMessage}" \
    -o jsonc 2>/dev/null || true
}

# Best single view of "what's actually stuck": every resource with its
# provisioningState. Discovery children usually show 'Deleting' for hours
# when the cascade is jammed.
dump_resource_states() {
  az resource list -g "$RESOURCE_GROUP" \
    --query "[].{name:name,type:type,state:provisioningState}" -o table 2>/dev/null || true
}

# Full unfiltered failure dump used when the script is convinced things are
# stuck. This is where the NSG-in-use and concurrent-DELETE errors surface.
dump_all_recent_failures() {
  local since_min="$1"
  az monitor activity-log list -g "$RESOURCE_GROUP" --offset "${since_min}m" \
    --query "[?status.value=='Failed'].{time:eventTimestamp,op:operationName.localizedValue,code:properties.statusCode,msg:properties.statusMessage}" \
    -o jsonc 2>/dev/null || true
}

print_deadlock_hints() {
  err ""
  err "  Known deadlock patterns and unblocks:"
  err ""
  err "  A. NSG in use by subnet (InUseNetworkSecurityGroupCannotBeDeleted)"
  err "     Root cause: SC's AKS cluster (in the SC MRG) still holds the subnet, which holds the NSG."
  err "     Unblock (only works if the RG is not yet in Deleting state):"
  err "       az network vnet subnet update -g ${RESOURCE_GROUP} \\"
  err "         --vnet-name <vnet-name> -n aksSubnet --network-security-group ''"
  err ""
  err "  B. Concurrent DELETE on workspace/nodepool (InvalidResourceOperation)"
  err "     Root cause: the RG-cascade issued a delete while a previous one is still in flight."
  err "     Unblock: wait 5-10 min for the in-flight op to complete, then re-run this script."
  err ""
  err "  C. Everything else stuck for hours with no failures logged"
  err "     Try the compute force-drain variant on the RG delete:"
  err "       az group delete -n ${RESOURCE_GROUP} --yes \\"
  err "         --force-deletion-types Microsoft.Compute/virtualMachineScaleSets"
  err ""
}

if $SKIP_RG_DELETE; then
  log "step 2: SKIPPED -- --abandon-orphan-vnet is set and the RG is tagged as orphaned"
  log "         RG '${RESOURCE_GROUP}' will remain until the orphaned SAL is purged"
elif az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
  log "step 2: deleting resource group '${RESOURCE_GROUP}' (async; timeout ${RG_DELETE_TIMEOUT}m)..."

  # Fire and forget; we poll for completion below.
  if ! az group delete --name "$RESOURCE_GROUP" --yes --no-wait; then
    err "failed to submit RG delete request"
    exit 1
  fi

  start_ts=$(date +%s)
  last_count=$(count_rg_resources)
  last_change_ts=$start_ts
  last_activity_scan_ts=0
  last_state_dump_ts=0

  log "  initial resource count: ${last_count}"
  log "  initial state:"
  dump_resource_states | sed 's/^/    /'

  while true; do
    sleep "$POLL_INTERVAL"

    if ! az group show --name "$RESOURCE_GROUP" >/dev/null 2>&1; then
      ok "resource group '${RESOURCE_GROUP}' deleted"
      break
    fi

    now_ts=$(date +%s)
    elapsed_min=$(( (now_ts - start_ts) / 60 ))
    current_count=$(count_rg_resources)

    if [[ "$current_count" != "$last_count" ]]; then
      log "  [${elapsed_min}m elapsed] resources remaining: ${current_count} (was ${last_count})"
      last_count=$current_count
      last_change_ts=$now_ts
    else
      stall_min=$(( (now_ts - last_change_ts) / 60 ))
      log "  [${elapsed_min}m elapsed] resources remaining: ${current_count} (no change for ${stall_min}m)"

      if (( stall_min >= STALL_WARN_MINUTES )); then
        warn "  no progress for ${stall_min}m -- running full stall diagnostic"
        warn "  current resource states:"
        dump_resource_states | sed 's/^/    /' >&2

        failures=$(scan_real_failures 30)
        if [[ -n "$failures" && "$failures" != "[]" ]]; then
          err "  REAL delete failures in last 30m (post-filter):"
          printf "%s\n" "$failures" >&2
        else
          warn "  no real failures in filtered scan -- dumping ALL failures unfiltered:"
          all_failures=$(dump_all_recent_failures 60)
          if [[ -n "$all_failures" && "$all_failures" != "[]" ]]; then
            printf "%s\n" "$all_failures" >&2
          else
            warn "  no failures in activity log at all -- delete may be waiting on an underlying async op (e.g. AKS cluster in the SC MRG)."
          fi
        fi

        print_deadlock_hints
        # reset the stall clock so we don't spam every minute
        last_change_ts=$now_ts
      fi
    fi

    # Periodic proactive activity-log scan for real failures.
    if (( (now_ts - last_activity_scan_ts) / 60 >= ACTIVITY_LOG_EVERY )); then
      failures=$(scan_real_failures "$ACTIVITY_LOG_EVERY")
      if [[ -n "$failures" && "$failures" != "[]" ]]; then
        warn "  real delete failures detected in last ${ACTIVITY_LOG_EVERY}m:"
        printf "%s\n" "$failures"
      fi
      last_activity_scan_ts=$now_ts
    fi

    # Periodic state-table dump so users can see what is 'Deleting' vs 'Succeeded'
    # without opening a second terminal.
    if (( (now_ts - last_state_dump_ts) / 60 >= ACTIVITY_LOG_EVERY )); then
      log "  current resource states:"
      dump_resource_states | sed 's/^/    /'
      last_state_dump_ts=$now_ts
    fi

    if (( elapsed_min >= RG_DELETE_TIMEOUT )); then
      err "timeout: RG '${RESOURCE_GROUP}' still exists after ${RG_DELETE_TIMEOUT}m"
      err "  final resource states:"
      dump_resource_states | sed 's/^/    /' >&2
      err "  final unfiltered failures (last 2h):"
      dump_all_recent_failures 120 >&2 || true
      print_deadlock_hints
      err "  the delete request is still in-flight in Azure; safe to re-run this script later, or increase --timeout"
      exit 1
    fi
  done
else
  log "step 2: RG '${RESOURCE_GROUP}' already gone"
fi

# ---- step 3: force-delete surviving MRGs ------------------------------------

delete_mrg_with_retry() {
  local mrg="$1"
  local attempt=1

  while (( attempt <= MRG_RETRIES )); do
    if ! az group show --name "$mrg" >/dev/null 2>&1; then
      ok "  MRG '${mrg}' already gone"
      return 0
    fi

    log "  attempt ${attempt}/${MRG_RETRIES}: deleting MRG '${mrg}'..."
    if az group delete --name "$mrg" --yes --force-deletion-types Microsoft.Compute/virtualMachineScaleSets 2>/dev/null; then
      ok "  MRG '${mrg}' deleted"
      return 0
    fi

    warn "  attempt ${attempt} failed for '${mrg}'; retrying in ${MRG_RETRY_DELAY}s..."
    sleep "$MRG_RETRY_DELAY"
    (( attempt++ ))
  done

  err "  MRG '${mrg}' could not be deleted after ${MRG_RETRIES} attempts. Investigate manually:"
  err "    az group show --name ${mrg}"
  err "    az resource list --resource-group ${mrg} -o table"
  return 1
}

if [[ ${#MRGS[@]} -gt 0 ]]; then
  log "step 3: cleaning up managed resource groups..."
  failed=0
  for mrg in "${MRGS[@]}"; do
    delete_mrg_with_retry "$mrg" || failed=1
  done
  if (( failed )); then
    err "one or more MRGs failed to delete -- see messages above"
    exit 1
  fi
else
  log "step 3: no MRGs to delete"
fi

echo
ok "teardown complete."
