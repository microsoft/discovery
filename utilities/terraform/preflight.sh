#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# preflight.sh
#
# Validate that a subscription + region + SKU combo is actually viable
# BEFORE running `terraform apply`. Only performs DETERMINISTIC checks --
# things Azure will reject on every attempt until you change your inputs or
# open a support ticket. Transient failures (AKS capacity, throttling, RP
# hiccups) are not attempted here because a passing check today would give
# false confidence tomorrow.
#
# Four checks, all deterministic:
#
#   1. Microsoft.Discovery RP is registered on the subscription.
#   2. Target region is not on the maintained known-bad list. This catches
#      RP-level region gates that no Azure API surfaces (e.g. `eastus2`
#      currently rejects new supercomputer creates even though the RP
#      metadata claims support). See KNOWN_BAD_REGIONS below and
#      README Step 1.4 for the source-of-truth table.
#   3. AKS system-pool VM SKU (Discovery RP internal default) and the
#      configured node_pool_vm_size are both allowlisted on the subscription
#      in the region. `NotAvailableForSubscription` is a hard block that
#      requires a support ticket.
#   4. Compute cores quota (family + regional total) is sufficient for
#      node_pool_max_node_count * vCPUs + AKS system pool.
#
# Additional checks are auto-discovered from ./preflight-checks/. Each file
# there is an encapsulated module (one concern per file) that can be removed
# with `rm preflight-checks/<file>` without touching this orchestrator.
# See ./preflight-checks/README.md for the module contract.
#
# Deliberately NOT checked:
#
#   * RP metadata region list -- unreliable; see check 2 for the workaround.
#   * AKS regional capacity (AKSCapacityHeavyUsage) -- transient, not
#     queryable in advance.
#   * Chat model catalog -- no listable RP endpoint at 2026-02-01-preview.
#
# Usage:
#   ./preflight.sh                    # reads terraform.tfvars if present
#   ./preflight.sh -l uksouth         # override location
#   ./preflight.sh -l uksouth -v Standard_D4s_v5 -n 3
#
# Exit codes:
#   0  all checks passed (WARN entries do not fail)
#   1  at least one FAIL check
#   2  bad invocation or missing tooling
# -----------------------------------------------------------------------------

set -euo pipefail

# ---- constants -------------------------------------------------------------
#
# The Discovery RP internally provisions an AKS system pool for the
# supercomputer using this SKU. This is what failed in eastus during the
# port -- the SC's own PUT was rejected because the sub was not allowlisted
# for D4s_v6, even though we had never touched the node_pool_vm_size yet.
# This is NOT a Terraform variable; it's baked into the RP.
AKS_SYSTEM_VM_SIZE="Standard_D4s_v6"

# ---- pretty output ----------------------------------------------------------

if [[ -t 1 ]]; then
  C_INFO=$'\033[36m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_OK=$'\033[32m'; C_OFF=$'\033[0m'
else
  C_INFO=""; C_WARN=""; C_ERR=""; C_OK=""; C_OFF=""
fi

pass() { printf "  %sPASS%s  %s\n" "$C_OK"   "$C_OFF" "$*"; }
warn() { printf "  %sWARN%s  %s\n" "$C_WARN" "$C_OFF" "$*"; WARN_COUNT=$((WARN_COUNT+1)); }
fail() { printf "  %sFAIL%s  %s\n" "$C_ERR"  "$C_OFF" "$*"; FAIL_COUNT=$((FAIL_COUNT+1)); }
info() { printf "%s[preflight]%s %s\n" "$C_INFO" "$C_OFF" "$*"; }

WARN_COUNT=0
FAIL_COUNT=0

# ---- arg parsing ------------------------------------------------------------

LOCATION=""
NODE_POOL_VM_SIZE=""
NODE_POOL_MAX_COUNT=""

usage() {
  sed -n '3,32p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -l|--location)     LOCATION="$2"; shift 2 ;;
    -v|--vm-size)      NODE_POOL_VM_SIZE="$2"; shift 2 ;;
    -n|--max-nodes)    NODE_POOL_MAX_COUNT="$2"; shift 2 ;;
    -h|--help)         usage 0 ;;
    *)                 echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done

# ---- tooling ----------------------------------------------------------------

command -v az >/dev/null || { echo "az CLI not on PATH" >&2; exit 2; }
command -v jq >/dev/null || { echo "jq not on PATH" >&2; exit 2; }

if ! az account show >/dev/null 2>&1; then
  echo "not signed in. Run: az login" >&2
  exit 2
fi

# ---- resolve values --------------------------------------------------------
#
# Precedence (highest to lowest):
#   1. --flag on the command line
#   2. terraform.tfvars (user override, if present)
#   3. variables.tf `default = ...` line (source of truth)
#
# There are NO hardcoded defaults in this script. That prevents drift from
# variables.tf, which repeatedly bit us during the bicep port.

read_tfvar() {
  # Read `key = "value"` (or bare number) from terraform.tfvars.
  # Uses POSIX character classes -- BSD sed on macOS does not support `\s`.
  local key="$1"
  [[ -f terraform.tfvars ]] || return 0
  grep -E "^[[:space:]]*${key}[[:space:]]*=" terraform.tfvars 2>/dev/null \
    | head -n 1 \
    | sed -E "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*//; s/^\"//; s/\"[[:space:]]*$//; s/[[:space:]]*$//"
}

read_tf_default() {
  # Read the `default = ...` from variables.tf for a given `variable "key" {}`
  # block. Uses awk to scope to the block boundaries so a `default` line for
  # a different variable can't leak in. Uses POSIX character classes because
  # BSD awk on macOS does not understand `\s`.
  local key="$1"
  [[ -f variables.tf ]] || return 0
  awk -v k="$key" '
    $0 ~ "^variable \"" k "\" \\{" { in_block = 1; next }
    in_block && /^\}/                                { in_block = 0 }
    in_block && /^[[:space:]]*default[[:space:]]*=/  {
      sub(/^[[:space:]]*default[[:space:]]*=[[:space:]]*/, "")
      sub(/^"/, ""); sub(/"[[:space:]]*$/, "")
      sub(/[[:space:]]*$/, "")
      print
      exit
    }
  ' variables.tf
}

resolve() {
  # Resolve a value using the CLI -> tfvars -> variables.tf precedence.
  # Fails with a clear error if nothing supplied it.
  local cli_value="$1"
  local tfvar_key="$2"
  local label="$3"

  local v="$cli_value"
  [[ -z "$v" ]] && v="$(read_tfvar     "$tfvar_key" || true)"
  [[ -z "$v" ]] && v="$(read_tf_default "$tfvar_key" || true)"

  if [[ -z "$v" ]]; then
    echo "could not resolve '${label}' -- pass it on the command line, set it in terraform.tfvars, or add a default to variables.tf" >&2
    exit 2
  fi
  echo "$v"
}

LOCATION=$(resolve            "$LOCATION"            "location"                 "location")
NODE_POOL_VM_SIZE=$(resolve   "$NODE_POOL_VM_SIZE"   "node_pool_vm_size"        "node_pool_vm_size")
NODE_POOL_MAX_COUNT=$(resolve "$NODE_POOL_MAX_COUNT" "node_pool_max_node_count" "node_pool_max_node_count")

SUB_ID=$(az account show --query id -o tsv)
SUB_NAME=$(az account show --query name -o tsv)

echo
info "preflight configuration"
info "  subscription:       ${SUB_NAME} (${SUB_ID})"
info "  location:           ${LOCATION}"
info "  node pool VM size:  ${NODE_POOL_VM_SIZE}"
info "  node pool max:      ${NODE_POOL_MAX_COUNT}"
info "  AKS system SKU:     ${AKS_SYSTEM_VM_SIZE} (Discovery RP internal)"
echo

# ---- check 1: Discovery RP is registered on the subscription ---------------

info "1. Discovery resource provider"
RP_STATE=$(az provider show --namespace Microsoft.Discovery --query registrationState -o tsv 2>/dev/null || echo "NotFound")
case "$RP_STATE" in
  Registered)   pass "Microsoft.Discovery is Registered" ;;
  Registering)  warn "Microsoft.Discovery is Registering -- wait or run 'az provider register -n Microsoft.Discovery'" ;;
  *)            fail "Microsoft.Discovery not registered (state=${RP_STATE}). Run: az provider register -n Microsoft.Discovery" ;;
esac

# ---- check 2: RP metadata says region supports the resource types we need --

info "2. Known-bad regions (documented deterministic failures)"

# Known-bad regions: the RP metadata advertises support, but the RP itself
# rejects new-resource creates. Confirmed with real PUT calls, not folklore.
# These are DETERMINISTIC failures -- they'll fail every attempt until
# Microsoft ships an RP update. Not queryable via any Azure API today.
#
# Remove entries here when the underlying gap is fixed. Re-verify before
# removing by running `terraform apply` end-to-end in the region.
#
#   eastus2 -- "Creation of new Supercomputer resources is not supported in
#              region 'eastus2'." (observed 2026-07-09 on the SC + storage
#              container PUTs; async LRO fails ~30m after PUT is accepted.)
KNOWN_BAD_REGIONS=(eastus2)

loc_norm=$(echo "$LOCATION" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
matched_bad=false
for bad in "${KNOWN_BAD_REGIONS[@]}"; do
  if [[ "$bad" == "$loc_norm" ]]; then
    fail "  '${LOCATION}' is on the known-bad list. The Discovery RP advertises support but rejects new supercomputer/storagecontainer creates. Pick another region (see README Step 1.4)."
    matched_bad=true
    break
  fi
done
$matched_bad || pass "  ${LOCATION} is not on the known-bad list"

# ---- check 3: VM SKUs are allowlisted on this subscription ------------------

check_sku_available() {
  local sku="$1"
  local label="$2"

  local restrictions
  restrictions=$(az vm list-skus --location "$LOCATION" --resource-type virtualMachines \
                    --query "[?name=='${sku}'].restrictions[].reasonCode | [0]" -o tsv 2>/dev/null)

  if [[ -z "$restrictions" ]]; then
    pass "  ${label} '${sku}' is available in ${LOCATION}"
    return 0
  fi

  case "$restrictions" in
    NotAvailableForSubscription)
      fail "  ${label} '${sku}' is NotAvailableForSubscription in ${LOCATION}. Choose another region or request the SKU via support."
      ;;
    QuotaId)
      fail "  ${label} '${sku}' blocked by QuotaId restriction in ${LOCATION}."
      ;;
    *)
      warn "  ${label} '${sku}' has restriction '${restrictions}' in ${LOCATION}"
      ;;
  esac
  return 1
}

info "3. VM SKU availability for subscription in '${LOCATION}'"
check_sku_available "$AKS_SYSTEM_VM_SIZE" "AKS system pool SKU (Discovery RP default)" || true
if [[ "$NODE_POOL_VM_SIZE" != "$AKS_SYSTEM_VM_SIZE" ]]; then
  check_sku_available "$NODE_POOL_VM_SIZE" "Node pool SKU"                        || true
fi

# ---- check 4: compute cores quota ------------------------------------------
#
# The relevant family is derived from the VM SKU name. Discovery + AKS both
# count against the standard "standardDSv..." / "standardDDv..." families.
# We look up the exact family from the SKU listing.

info "4. Compute cores quota in '${LOCATION}'"

sku_family=$(az vm list-skus --location "$LOCATION" --resource-type virtualMachines \
              --query "[?name=='${NODE_POOL_VM_SIZE}'] | [0].family" -o tsv 2>/dev/null)
sku_vcpus=$(az vm list-skus --location "$LOCATION" --resource-type virtualMachines \
              --query "[?name=='${NODE_POOL_VM_SIZE}'] | [0].capabilities[?name=='vCPUs'].value | [0]" -o tsv 2>/dev/null)

if [[ -z "$sku_family" || -z "$sku_vcpus" ]]; then
  warn "  could not resolve family/vCPU count for '${NODE_POOL_VM_SIZE}' (likely because the SKU is not available). Skipping quota math."
else
  required_cores=$(( NODE_POOL_MAX_COUNT * sku_vcpus ))
  # The AKS system pool consumes cores too; assume 1 x AKS_SYSTEM_VM_SIZE.
  sys_vcpus=$(az vm list-skus --location "$LOCATION" --resource-type virtualMachines \
                --query "[?name=='${AKS_SYSTEM_VM_SIZE}'] | [0].capabilities[?name=='vCPUs'].value | [0]" -o tsv 2>/dev/null)
  [[ -n "$sys_vcpus" ]] && required_cores=$(( required_cores + sys_vcpus ))

  quota_row=$(az vm list-usage --location "$LOCATION" \
                --query "[?name.value=='${sku_family}'] | [0]" -o json 2>/dev/null)
  if [[ -z "$quota_row" || "$quota_row" == "null" ]]; then
    warn "  no quota row for family '${sku_family}' in ${LOCATION}"
  else
    limit=$(echo "$quota_row"    | jq -r '.limit')
    current=$(echo "$quota_row"  | jq -r '.currentValue')
    available=$(( limit - current ))
    if (( available >= required_cores )); then
      pass "  family '${sku_family}': ${current}/${limit} used, ${available} free, need ${required_cores}"
    else
      fail "  family '${sku_family}': only ${available} cores free, need ${required_cores}. Request a quota increase or reduce node_pool_max_node_count."
    fi
  fi

  # Regional total quota check
  total_row=$(az vm list-usage --location "$LOCATION" \
                --query "[?name.value=='cores'] | [0]" -o json 2>/dev/null)
  if [[ -n "$total_row" && "$total_row" != "null" ]]; then
    tlimit=$(echo "$total_row"   | jq -r '.limit')
    tcurrent=$(echo "$total_row" | jq -r '.currentValue')
    tavailable=$(( tlimit - tcurrent ))
    if (( tavailable >= required_cores )); then
      pass "  regional Total Cores: ${tcurrent}/${tlimit} used, ${tavailable} free"
    else
      fail "  regional Total Cores: only ${tavailable} free, need ${required_cores}. Request a Total Cores increase."
    fi
  fi
fi

# ---- additional checks (auto-discovered) -----------------------------------
#
# Every executable-looking file in ./preflight-checks/ named `NN-*.sh` is
# sourced here in numeric order. Each module runs top-level using the pass /
# warn / fail / info helpers and the resolved LOCATION / NODE_POOL_VM_SIZE /
# NODE_POOL_MAX_COUNT / AKS_SYSTEM_VM_SIZE / SUB_ID globals defined above.
#
# To disable a module: `rm preflight-checks/<file>` (or rename its prefix out
# of the [0-9] glob). No changes to this orchestrator required.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "${SCRIPT_DIR}/preflight-checks" ]]; then
  # Nullglob so the loop is a no-op if the directory is empty.
  shopt -s nullglob
  for _check_module in "${SCRIPT_DIR}"/preflight-checks/[0-9]*.sh; do
    # shellcheck disable=SC1090
    source "$_check_module"
  done
  shopt -u nullglob
  unset _check_module
fi

# ---- summary ----------------------------------------------------------------

echo
if (( FAIL_COUNT > 0 )); then
  printf "%s[preflight]%s %d FAIL, %d WARN -- do NOT run terraform apply yet\n" "$C_ERR" "$C_OFF" "$FAIL_COUNT" "$WARN_COUNT"
  exit 1
elif (( WARN_COUNT > 0 )); then
  printf "%s[preflight]%s %d WARN, 0 FAIL -- safe to proceed, review warnings above\n" "$C_WARN" "$C_OFF" "$WARN_COUNT"
  exit 0
else
  printf "%s[preflight]%s all checks passed\n" "$C_OK" "$C_OFF"
  exit 0
fi
