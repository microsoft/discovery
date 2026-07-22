#!/usr/bin/env bash
#
# delete-all-resources-2026-06-01.sh
#
# Deletes all Microsoft.Discovery and supporting Azure resources in a resource
# group using the 2026-06-01 GA API version, in strict dependency order:
#
#   1) DataAssets            (Microsoft.Discovery/dataContainers/dataAssets)
#   2) StorageAssets         (Microsoft.Discovery/storageContainers/storageAssets)
#   3) Data plane agents     (workspace DP /projects/{p}/agents/{a})
#   4) Projects              (Microsoft.Discovery/workspaces/projects)
#   5) Agents                (Microsoft.Discovery/agents) — clear blocking links first
#   6) ChatModelDeployments  (Microsoft.Discovery/workspaces/chatModelDeployments)
#   7) Tools                 (Microsoft.Discovery/tools) — clear LinkedAgentIds first
#   8) Workflows             (Microsoft.Discovery/workflows)
#   9) Models                (Microsoft.Discovery/models)
#  10) DataContainers        (Microsoft.Discovery/dataContainers)
#  11) StorageContainers     (Microsoft.Discovery/storageContainers)
#  12) Workspace PECP/PEC    (Microsoft.Discovery/workspaces/privateEndpoint*)
#  13) Bookshelf PECP/PEC    (Microsoft.Discovery/bookshelves/privateEndpoint*)
#  14) Unlink Workspaces     (PATCH supercomputerIds to [])
#  15) Workspaces            (Microsoft.Discovery/workspaces)
#  16) Bookshelves           (Microsoft.Discovery/bookshelves)
#  17) NodePools             (Microsoft.Discovery/supercomputers/nodePools)
#  18) Supercomputers        (Microsoft.Discovery/supercomputers)
#  19) Storages              (Microsoft.Discovery/storages)
#  20) Storage Accounts      (Microsoft.Storage/storageAccounts)
#  21) UAMIs                 (Microsoft.ManagedIdentity/userAssignedIdentities)
#  22) Virtual Networks      (Microsoft.Network/virtualNetworks)
#      – Subnet delegations are removed and orphaned service-association
#        links are cleaned up before VNet deletion is attempted.
#      – NSGs are NOT deleted individually; they are removed when the
#        resource group is deleted.
#  23) Any remaining resources
#  24) Delete the resource group itself (if empty)
#
# Uses a strict GA-only delete path for Microsoft.Discovery resources.
# If any Discovery delete fails with api-version 2026-06-01, the script exits.
#
# Cross-platform: Linux (including WSL) and Git Bash on Windows.
# Requires: az CLI (already logged in), jq, curl
#
# Usage:
#   ./delete-all-resources-2026-06-01.sh \
#       -s <subscription-id> -g <resource-group-name> \
#       [--dry-run] [--verbose] [--force] [--continue-on-error]
#
set -euo pipefail

# Prevent Git Bash (MSYS2) from converting /subscriptions/... paths to
# C:/Program Files/Git/subscriptions/...
export MSYS_NO_PATHCONV=1

###############################################################################
# Constants
###############################################################################
API_VERSION="2026-06-01"
# Data-plane agent endpoint API version. Defaults to the same GA version used
# for ARM calls. Exposed as a separate variable (overridable via DP_API_VERSION
# env var) so the DP version can be flipped independently for diagnosis without
# touching control-plane behavior.
DP_API_VERSION="${DP_API_VERSION:-2026-06-01}"
ARM_BASE="https://management.azure.com"
POLL_INTERVAL_SECONDS=15
MAX_POLL_ATTEMPTS=240   # ~60 min max wait per resource
DELETE_RETRY_ATTEMPTS=6         # retries for transient errors (e.g. nested-resource cache lag after deleting children)
DELETE_RETRY_INTERVAL_SECONDS=20

###############################################################################
# Defaults
###############################################################################
SUBSCRIPTION_ID=""
RESOURCE_GROUP=""
TENANT_ID=""
DRY_RUN=false
VERBOSE=false
FORCE=false
CONTINUE_ON_ERROR=true

###############################################################################
# Usage
###############################################################################
usage() {
  cat <<EOF
Usage: $0 -s <subscription-id> -g <resource-group> [OPTIONS]

Required:
  -s <id>       Azure subscription ID
  -g <name>     Resource group name

Options:
  --dry-run             Print deletion plan without deleting anything
  --verbose             Print REST calls and responses (tokens redacted)
  --force               Skip the confirmation prompt
  --continue-on-error   Compatibility option; failures are collected by default
  -h, --help            Show this help and exit
EOF
  exit "${1:-0}"
}

###############################################################################
# Argument parsing
###############################################################################
parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -s)
        [[ $# -ge 2 ]] || { echo "Error: -s requires a subscription ID."; usage 1; }
        SUBSCRIPTION_ID="$2"; shift 2 ;;
      -g)
        [[ $# -ge 2 ]] || { echo "Error: -g requires a resource group name."; usage 1; }
        RESOURCE_GROUP="$2"; shift 2 ;;
      --dry-run) DRY_RUN=true;  shift ;;
      --verbose) VERBOSE=true;  shift ;;
      --force)   FORCE=true;    shift ;;
      --continue-on-error) CONTINUE_ON_ERROR=true; shift ;;
      -h|--help) usage 0 ;;
      *)         echo "Unknown option: $1"; usage 1 ;;
    esac
  done

  if [[ -z "$SUBSCRIPTION_ID" || -z "$RESOURCE_GROUP" ]]; then
    echo "Error: -s and -g are required."
    usage 1
  fi
}

###############################################################################
# Logging helpers
###############################################################################
log()     { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*"; }
info()    { log "INFO  $*"; }
warn()    { log "WARN  $*"; }
die()     { log "ERROR $*"; exit 1; }
verbose() { [[ "$VERBOSE" == true ]] && log "DEBUG $*" || true; }

# Redact Bearer tokens from arbitrary text.
redact() { sed 's/Bearer [A-Za-z0-9_.\-]*/Bearer [REDACTED]/g'; }

# URL-encode a single path segment.
url_encode() {
  jq -rn --arg v "$1" '$v|@uri'
}

###############################################################################
# Prerequisites
###############################################################################
check_prereqs() {
  for cmd in az jq curl; do
    if ! command -v "$cmd" &>/dev/null; then
      die "'$cmd' is required but not found on PATH."
    fi
  done
}

###############################################################################
# Resource listing helpers
###############################################################################

# List resource IDs in the RG filtered by ARM resource type.
# Outputs one resource ID per line, sorted for deterministic ordering.
# $1 = ARM resource type (e.g. "Microsoft.Discovery/workspaces")
list_resources_by_type() {
  local rtype="$1"
  az resource list \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$SUBSCRIPTION_ID" \
    --resource-type "$rtype" \
    --query "[].id" -o tsv 2>/dev/null | tr -d '\r' | sort || true
}

# List ALL resources in the RG. One resource ID per line, sorted.
list_all_resources() {
  az resource list \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$SUBSCRIPTION_ID" \
    --query "[].id" -o tsv 2>/dev/null | tr -d '\r' | sort || true
}

###############################################################################
# Read lines into a named array (portable bash 4.3+)
###############################################################################
read_into_array() {
  local -n _arr=$1
  _arr=()
  local line
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    _arr+=("$line")
  done
}

###############################################################################
# Deletion: Microsoft.Discovery resources (az rest + polling)
#
# Uses ONLY the GA API version (2026-06-01). No fallback API versions are used.
# If deletion fails after retrying transient errors, the script exits.
###############################################################################
_try_delete_discovery_resource() {
  # Inner helper: attempt DELETE with a specific API version.
  # Returns 0 on success and 1 on failure.
  local resource_id="$1"
  local api_ver="$2"
  local url="${ARM_BASE}${resource_id}?api-version=${api_ver}"

  info "  DELETE attempt (api-version=${api_ver}): $resource_id"
  verbose "  DELETE $url"

  local retry=0 delete_accepted=false
  while true; do
    local del_output del_rc=0
    del_output=$(az rest --method DELETE --url "$url" -o none 2>&1) || del_rc=$?

    if [[ $del_rc -eq 0 ]]; then
      verbose "  DELETE returned success."
      delete_accepted=true
      break
    fi

    # 404 means the resource is already gone — treat as success.
    if echo "$del_output" | grep -qi 'not found'; then
      info "  Already deleted (404): $resource_id"
      return 0
    fi

    # ResourceDeletionValidateFailed — the RP's deletion validation callback
    # returned an error. Retry a few times in case RP state is still settling.
    if echo "$del_output" | grep -qiE 'ResourceDeletionValidateFailed|deletion validation failed'; then
      retry=$((retry + 1))
      if (( retry > DELETE_RETRY_ATTEMPTS )); then
        warn "  ResourceDeletionValidateFailed persisted after ${DELETE_RETRY_ATTEMPTS} retries (api-version=${api_ver})"
        info "  Last error: $(echo "$del_output" | head -c 300 | redact)"
        return 1
      fi
      warn "  Validation error (attempt ${retry}/${DELETE_RETRY_ATTEMPTS}), retrying in ${DELETE_RETRY_INTERVAL_SECONDS}s..."
      sleep "$DELETE_RETRY_INTERVAL_SECONDS"
      continue
    fi

    # Other transient errors — retry with backoff.
    if echo "$del_output" | grep -qiE 'CannotDeleteResource|Conflict|linked workspace|NameResolutionError|ConnectionError|MaxRetryError|getaddrinfo|Connection refused|timed out|ConnectionResetError'; then
      retry=$((retry + 1))
      if (( retry > DELETE_RETRY_ATTEMPTS )); then
        log "ERROR Retryable error persisted after ${DELETE_RETRY_ATTEMPTS} retries: $resource_id"
        log "ERROR Last payload:"
        echo "$del_output" | redact >&2
        return 1
      fi
      warn "  Transient error (attempt ${retry}/${DELETE_RETRY_ATTEMPTS}), retrying in ${DELETE_RETRY_INTERVAL_SECONDS}s..."
      verbose "  Response: $(echo "$del_output" | head -c 500 | redact)"
      sleep "$DELETE_RETRY_INTERVAL_SECONDS"
      continue
    fi

    # The requested API version is not supported for this resource type/location.
    if echo "$del_output" | grep -qiE 'NoRegisteredProviderFound|InvalidApiVersionParameter|The resource type .* could not be found|No registered resource provider found'; then
      warn "  api-version=${api_ver} is not supported for this resource type/location."
      verbose "  Response: $(echo "$del_output" | head -c 500 | redact)"
      return 1
    fi

    # Any other error body is a real failure.
    if echo "$del_output" | grep -qiE 'error|bad request|forbidden|unauthorized|invalid'; then
      log "ERROR Failed to delete: $resource_id"
      log "ERROR Status / payload:"
      echo "$del_output" | redact >&2
      return 1
    fi

    # Non-zero but no error keywords — likely 202 Accepted (async).
    verbose "  DELETE accepted (async). $(echo "$del_output" | redact)"
    delete_accepted=true
    break
  done

  # Poll GET until the resource returns 404 (confirmed gone).
  info "  Waiting for deletion to complete..."
  local attempt=0
  while (( attempt < MAX_POLL_ATTEMPTS )); do
    sleep "$POLL_INTERVAL_SECONDS"
    attempt=$((attempt + 1))

    local get_result get_rc=0
    get_result=$(az rest --method GET --url "${ARM_BASE}${resource_id}?api-version=${api_ver}" --output json 2>&1) || get_rc=$?

    if [[ $get_rc -ne 0 ]]; then
      # GET failed → resource is gone.
      info "  Confirmed deleted: $resource_id"
      return 0
    fi

    verbose "  GET response: $(echo "$get_result" | head -c 500 | redact)"

    local prov_state
    prov_state=$(echo "$get_result" | jq -r '.properties.provisioningState // empty' 2>/dev/null || true)

    if [[ "${prov_state,,}" == "failed" ]]; then
      log "ERROR Resource entered Failed state during deletion: $resource_id"
      echo "$get_result" | jq . 2>/dev/null | redact >&2 || echo "$get_result" | redact >&2
      return 1
    fi

    info "  Still deleting (provisioningState=${prov_state:-unknown}, attempt ${attempt}/${MAX_POLL_ATTEMPTS})..."
  done

  log "ERROR Timed out waiting for deletion of: $resource_id"
  return 1
}

delete_discovery_resource() {
  local resource_id="$1"

  # GA-only strategy: use API_VERSION and fail fast on any error.
  local rc=0
  _try_delete_discovery_resource "$resource_id" "$API_VERSION" || rc=$?
  [[ $rc -eq 0 ]] && return 0
  die "Microsoft.Discovery delete failed using GA api-version ${API_VERSION}: ${resource_id}"
}

###############################################################################
# Deletion: non-Discovery resources (az resource delete)
###############################################################################
delete_generic_resource() {
  local resource_id="$1"
  info "  Deleting (az CLI): $resource_id"
  verbose "  az resource delete --ids \"$resource_id\""

  local del_output del_rc=0
  del_output=$(az resource delete --ids "$resource_id" 2>&1) || del_rc=$?

  if [[ $del_rc -ne 0 ]]; then
    log "ERROR Failed to delete resource: $resource_id"
    log "ERROR Status / payload:"
    echo "$del_output" | redact >&2
    if [[ "$CONTINUE_ON_ERROR" == true ]]; then
      FAILED_RESOURCES+=("$resource_id")
      return 1
    fi
    exit 1
  fi

  verbose "  Response: $(echo "$del_output" | head -c 500 | redact)"
  info "  Deleted: $resource_id"
}

###############################################################################
# Smart dispatch: pick deletion method based on resource type in the ID
###############################################################################
delete_resource() {
  local resource_id="$1"
  if echo "$resource_id" | grep -qi 'Microsoft\.Discovery/'; then
    delete_discovery_resource "$resource_id"
  else
    delete_generic_resource "$resource_id"
  fi
}

###############################################################################
# Clear inbound Agent links that block ARM Agent deletion.
# Project deletion should normally delink Agents, but cycles or stale metadata can
# still leave LinkedProjectIds/LinkedAgentIds behind. This best-effort PATCH makes
# the cleanup script resilient without changing service code.
###############################################################################
clear_agent_blocking_links() {
  local resource_id="$1"
  local url="${ARM_BASE}${resource_id}?api-version=${API_VERSION}"

  info "  Clearing blocking Agent links before deletion: $resource_id"

  if [[ "$DRY_RUN" == true ]]; then
    info "  [DRY RUN] Would PATCH Agent internalMetadata link arrays to [] on: $resource_id"
    return 0
  fi

  local patch_body='{"properties":{"internalMetadata":{"linkedProjectIds":[],"linkedAgentIds":[]}}}'
  local patch_output patch_rc=0
  patch_output=$(az rest --method PATCH --url "$url" \
    --headers "Content-Type=application/json" \
    --body "$patch_body" --output json 2>&1) || patch_rc=$?

  if [[ $patch_rc -ne 0 ]]; then
    if echo "$patch_output" | grep -qi 'not found'; then
      info "  Agent already deleted (404) — skipping link cleanup."
      return 0
    fi
    warn "  PATCH to clear Agent blocking links failed (rc=$patch_rc). Will attempt deletion anyway."
    verbose "  PATCH response: $(echo "$patch_output" | head -c 500 | redact)"
    return 0
  fi

  local prov_state
  prov_state=$(echo "$patch_output" | jq -r '.properties.provisioningState // empty' 2>/dev/null || true)
  if [[ "${prov_state,,}" == "succeeded" ]]; then
    info "  Agent blocking links cleared (immediate)."
    return 0
  fi

  local attempt=0
  while (( attempt < MAX_POLL_ATTEMPTS )); do
    sleep "$POLL_INTERVAL_SECONDS"
    attempt=$((attempt + 1))

    local get_result get_rc=0
    get_result=$(az rest --method GET --url "$url" --output json 2>&1) || get_rc=$?
    if [[ $get_rc -ne 0 ]]; then
      info "  Agent gone during PATCH propagation — continuing."
      return 0
    fi

    prov_state=$(echo "$get_result" | jq -r '.properties.provisioningState // empty' 2>/dev/null || true)
    if [[ "${prov_state,,}" == "succeeded" ]]; then
      info "  Agent blocking links cleared."
      return 0
    fi

    if [[ "${prov_state,,}" == "failed" ]]; then
      warn "  Agent entered Failed state during link cleanup — will attempt deletion anyway."
      return 0
    fi

    info "  Still clearing Agent links (provisioningState=${prov_state:-unknown}, attempt ${attempt}/${MAX_POLL_ATTEMPTS})..."
  done

  warn "  Timed out waiting for Agent link cleanup — will attempt deletion anyway."
  return 0
}

###############################################################################
# Unlink: PATCH workspace to remove dependencies before deletion
###############################################################################
unlink_workspace_dependencies() {
  local resource_id="$1"
  local url="${ARM_BASE}${resource_id}?api-version=${API_VERSION}"

  info "  Unlinking supercomputers from workspace: $resource_id"
  verbose "  PATCH $url"

  if [[ "$DRY_RUN" == true ]]; then
    info "  [DRY RUN] Would PATCH supercomputerIds to [] on: $resource_id"
    return 0
  fi

  local patch_body='{"properties":{"supercomputerIds":[]}}'
  local patch_output patch_rc=0
  patch_output=$(az rest --method PATCH --url "$url" \
    --headers "Content-Type=application/json" \
    --body "$patch_body" --output json 2>&1) || patch_rc=$?

  if [[ $patch_rc -ne 0 ]]; then
    # 404 means the workspace is already gone — nothing to unlink.
    if echo "$patch_output" | grep -qi 'not found'; then
      info "  Workspace already deleted (404) — skipping unlink: $resource_id"
      return 0
    fi
    log "ERROR Failed to unlink dependencies from workspace: $resource_id"
    echo "$patch_output" | redact >&2
    if [[ "$CONTINUE_ON_ERROR" == true ]]; then
      FAILED_RESOURCES+=("$resource_id (unlink)")
      return 1
    fi
    exit 1
  fi

  verbose "  PATCH response: $(echo "$patch_output" | head -c 500 | redact)"

  # The PATCH may be async (202). Poll until provisioningState is Succeeded.
  local prov_state
  prov_state=$(echo "$patch_output" | jq -r '.properties.provisioningState // empty' 2>/dev/null || true)

  if [[ "${prov_state,,}" == "succeeded" ]]; then
    info "  Unlinked dependencies (immediate): $resource_id"
    return 0
  fi

  info "  Waiting for dependency unlink to complete (provisioningState=${prov_state:-unknown})..."
  local attempt=0
  while (( attempt < MAX_POLL_ATTEMPTS )); do
    sleep "$POLL_INTERVAL_SECONDS"
    attempt=$((attempt + 1))

    local get_result get_rc=0
    get_result=$(az rest --method GET --url "$url" --output json 2>&1) || get_rc=$?

    if [[ $get_rc -ne 0 ]]; then
      # Resource gone — unlink is moot.
      info "  Workspace deleted during dependency unlink — continuing: $resource_id"
      return 0
    fi

    prov_state=$(echo "$get_result" | jq -r '.properties.provisioningState // empty' 2>/dev/null || true)

    if [[ "${prov_state,,}" == "succeeded" ]]; then
      info "  Unlinked dependencies: $resource_id"
      return 0
    fi

    if [[ "${prov_state,,}" == "failed" ]]; then
      log "ERROR Workspace entered Failed state during unlink: $resource_id"
      echo "$get_result" | jq . 2>/dev/null | redact >&2 || echo "$get_result" | redact >&2
      if [[ "$CONTINUE_ON_ERROR" == true ]]; then
        FAILED_RESOURCES+=("$resource_id (unlink)")
        return 1
      fi
      exit 1
    fi

    info "  Still unlinking dependencies (provisioningState=${prov_state:-unknown}, attempt ${attempt}/${MAX_POLL_ATTEMPTS})..."
  done

  die "Timed out waiting for dependency unlink of: $resource_id"
}

###############################################################################
# Clear linked agent references from a Tool resource via ARM PATCH
#
# The Tool's InternalMetadata.LinkedAgentIds blocks deletion. The Delete
# validation checks each referenced agent via MetaRP (ARM IDs) or HTTP
# (data-plane URLs) and blocks if any appear to still exist — including when
# the check fails for transient reasons (the validator is pessimistic).
#
# Fix: PATCH the Tool to set internalMetadata.linkedAgentIds to [] BEFORE
# attempting DELETE. The Patch rule set does NOT validate LinkedAgentIds,
# so this succeeds. Once the Backend propagates the patch to MetaRP the
# subsequent DELETE validation finds an empty list and passes.
###############################################################################
clear_tool_linked_agents() {
  local resource_id="$1"
  local url="${ARM_BASE}${resource_id}?api-version=${API_VERSION}"

  # 1. GET the tool and inspect linkedAgentIds.
  local tool_json tool_rc=0
  tool_json=$(az rest --method GET --url "$url" --output json 2>&1) || tool_rc=$?
  if [[ $tool_rc -ne 0 ]]; then
    info "  Could not GET tool (rc=$tool_rc) — skipping LinkedAgentIds cleanup."
    return 0
  fi

  local linked_ids
  linked_ids=$(echo "$tool_json" | jq -r '.properties.internalMetadata.linkedAgentIds // [] | .[]' 2>/dev/null || true)

  if [[ -z "$linked_ids" ]]; then
    info "  Tool has no LinkedAgentIds — no pre-cleanup needed."
    return 0
  fi

  info "  Tool has LinkedAgentIds — PATCHing to clear before deletion:"
  while IFS= read -r aid; do
    [[ -z "$aid" ]] && continue
    info "    linked: $aid"
  done <<< "$linked_ids"

  if [[ "$DRY_RUN" == true ]]; then
    info "  [DRY RUN] Would PATCH internalMetadata.linkedAgentIds to [] on: $resource_id"
    return 0
  fi

  # 2. PATCH to clear linkedAgentIds.
  local patch_body='{"properties":{"internalMetadata":{"linkedAgentIds":[]}}}'
  local patch_output patch_rc=0
  patch_output=$(az rest --method PATCH --url "$url" \
    --headers "Content-Type=application/json" \
    --body "$patch_body" --output json 2>&1) || patch_rc=$?

  if [[ $patch_rc -ne 0 ]]; then
    if echo "$patch_output" | grep -qi 'not found'; then
      info "  Tool already deleted (404) — skipping LinkedAgentIds cleanup."
      return 0
    fi
    warn "  PATCH to clear LinkedAgentIds failed (rc=$patch_rc). Will attempt deletion anyway."
    info "  PATCH response: $(echo "$patch_output" | head -c 500 | redact)"
    return 0
  fi

  # 3. Wait for PATCH to propagate (async via Backend/Service Bus).
  local prov_state
  prov_state=$(echo "$patch_output" | jq -r '.properties.provisioningState // empty' 2>/dev/null || true)

  if [[ "${prov_state,,}" == "succeeded" ]]; then
    info "  LinkedAgentIds cleared (immediate)."
    return 0
  fi

  info "  Waiting for LinkedAgentIds PATCH to propagate (provisioningState=${prov_state:-unknown})..."
  local attempt=0
  while (( attempt < MAX_POLL_ATTEMPTS )); do
    sleep "$POLL_INTERVAL_SECONDS"
    attempt=$((attempt + 1))

    local get_result get_rc=0
    get_result=$(az rest --method GET --url "$url" --output json 2>&1) || get_rc=$?
    if [[ $get_rc -ne 0 ]]; then
      info "  Tool gone during PATCH propagation — continuing."
      return 0
    fi

    prov_state=$(echo "$get_result" | jq -r '.properties.provisioningState // empty' 2>/dev/null || true)

    if [[ "${prov_state,,}" == "succeeded" ]]; then
      info "  LinkedAgentIds cleared."
      return 0
    fi

    if [[ "${prov_state,,}" == "failed" ]]; then
      warn "  Tool entered Failed state during LinkedAgentIds PATCH — will attempt deletion anyway."
      return 0
    fi

    info "  Still patching (provisioningState=${prov_state:-unknown}, attempt ${attempt}/${MAX_POLL_ATTEMPTS})..."
  done

  warn "  Timed out waiting for LinkedAgentIds PATCH — will attempt deletion anyway."
  return 0
}

###############################################################################
# Data plane cleanup: delete agents from projects via workspace DP API
#
# 2026-06-01 project deletion validation blocks if agents exist
# in the project's data plane. These agents are NOT ARM resources and cannot
# be discovered by `az resource list`. This function:
#   1. Fetches the parent workspace to obtain its WorkspaceApiUri.
#   2. Lists agents via GET {WorkspaceApiUri}/projects/{name}/agents
#   3. Deletes each agent via DELETE {WorkspaceApiUri}/projects/{name}/agents/{a}
###############################################################################
cleanup_dataplane_agents_for_project() {
  local project_id="$1"

  # Extract workspace ID (parent) and project name from the resource ID.
  local workspace_id project_name
  workspace_id=$(echo "$project_id" | sed 's|/projects/.*||')
  project_name=$(echo "$project_id" | grep -oP '(?i)projects/\K[^/]+')

  if [[ -z "$workspace_id" || -z "$project_name" ]]; then
    warn "  Could not parse workspace/project from: $project_id"
    return 0
  fi

  # GET workspace to find WorkspaceApiUri.
  local ws_url="${ARM_BASE}${workspace_id}?api-version=${API_VERSION}"
  local ws_json ws_rc=0
  ws_json=$(az rest --method GET --url "$ws_url" --output json 2>&1) || ws_rc=$?

  if [[ $ws_rc -ne 0 ]]; then
    info "  Could not fetch workspace (rc=$ws_rc) — skipping DP agent cleanup for $project_id"
    return 0
  fi

  local workspace_api_uri
  workspace_api_uri=$(echo "$ws_json" | jq -r '.properties.workspaceApiUri // empty' 2>/dev/null || true)

  if [[ -z "$workspace_api_uri" ]]; then
    info "  Workspace has no WorkspaceApiUri — skipping DP agent cleanup for $project_id"
    return 0
  fi

  # Strip trailing slash if present.
  workspace_api_uri="${workspace_api_uri%/}"

  local encoded_project_name
  encoded_project_name=$(url_encode "$project_name")

  # Obtain bearer token for data plane (audience: https://discovery.azure.com).
  local token
  token=$(az account get-access-token --resource "https://discovery.azure.com" --query accessToken -o tsv 2>/dev/null | tr -d '\r' || true)
  if [[ -z "$token" ]]; then
    warn "  Could not acquire data plane access token — skipping DP agent cleanup for $project_id"
    return 0
  fi

  # List agents.
  local agents_url="${workspace_api_uri}/projects/${encoded_project_name}/agents?api-version=${DP_API_VERSION}"
  info "  Listing DP agents: GET $agents_url"
  local agents_response agents_code agents_json
  agents_response=$(curl -sS -w "\n%{http_code}" \
    -H "Authorization: Bearer $token" \
    -H "x-ms-client-tenant-id: ${TENANT_ID:-}" \
    "$agents_url" 2>/dev/null || true)
  agents_code=$(echo "$agents_response" | tail -n 1)
  agents_json=$(echo "$agents_response" | sed '$d')

  if [[ "$agents_code" != "200" ]]; then
    warn "  Failed to list data plane agents (HTTP ${agents_code:-unknown}) for project $project_name. Project deletion may still fail."
    if [[ -n "$agents_json" ]]; then
      warn "  Agents response: $(echo "$agents_json" | tr '\n' ' ' | head -c 1000 | redact)"
    fi
    return 0
  fi

  info "  Agents response: $(echo "$agents_json" | head -c 500 | redact)"

  local agent_names agent_count agent_list
  agent_names=$(echo "$agents_json" | jq -r '(.value // .)[]?.name // empty' 2>/dev/null | tr -d '\r' || true)

  if [[ -z "$agent_names" ]]; then
    info "  No data plane agents found for project $project_name."
    return 0
  fi

  agent_count=$(echo "$agent_names" | grep -c . || true)
  agent_list=$(echo "$agent_names" | paste -sd ',' -)
  info "  Discovered ${agent_count} data plane agent(s) in project '${project_name}': ${agent_list}"

  # Delete each agent.
  # NOTE: DP agent DELETE is a Long-Running Operation. The service returns 202
  # with an Operation-Location header; the agent is NOT gone until that LRO
  # terminalizes. We must (a) capture Operation-Location and (b) poll it,
  # matching the contract enforced by WorkspaceHttpClient.DeleteAgentAsync.
  local aname
  while IFS= read -r aname; do
    aname="${aname%$'\r'}"
    [[ -z "$aname" ]] && continue
    local encoded_agent_name del_url tmp_headers tmp_body del_code op_loc
    encoded_agent_name=$(url_encode "$aname")
    del_url="${workspace_api_uri}/projects/${encoded_project_name}/agents/${encoded_agent_name}?api-version=${DP_API_VERSION}"
    info "  Deleting data plane agent '${aname}' from project '${project_name}'..."
    verbose "  DELETE $del_url"

    if [[ "$DRY_RUN" == true ]]; then
      info "  [DRY RUN] Would DELETE agent: $aname"
      continue
    fi

    tmp_headers=$(mktemp)
    tmp_body=$(mktemp)
    del_code=$(curl -s -D "$tmp_headers" -o "$tmp_body" -w "%{http_code}" -X DELETE \
      -H "Authorization: Bearer $token" \
      -H "x-ms-client-tenant-id: ${TENANT_ID:-}" \
      "$del_url" 2>/dev/null || echo "000")

    if [[ "$del_code" == "404" ]]; then
      info "  Agent '${aname}' already gone (HTTP 404)."
      rm -f "$tmp_headers" "$tmp_body"
      continue
    fi

    if [[ "$del_code" != "200" && "$del_code" != "202" && "$del_code" != "204" ]]; then
      warn "  Failed to delete data plane agent '${aname}' (HTTP $del_code)."
      warn "  Response: $(tr -d '\r' < "$tmp_body" | head -c 1000 | redact)"
      rm -f "$tmp_headers" "$tmp_body"
      continue
    fi

    # 204 with no Operation-Location → already complete, no poll needed.
    op_loc=$(grep -i '^Operation-Location:' "$tmp_headers" 2>/dev/null \
              | tail -n 1 | sed -e 's/^[Oo]peration-[Ll]ocation:[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/\r$//')
    if [[ -z "$op_loc" ]]; then
      if [[ "$del_code" == "200" || "$del_code" == "204" ]]; then
        info "  Deleted data plane agent '${aname}' (HTTP $del_code, no LRO)."
      else
        warn "  Agent '${aname}' DELETE returned $del_code without Operation-Location. May still complete; will verify via LIST."
      fi
      rm -f "$tmp_headers" "$tmp_body"
      continue
    fi

    verbose "  DELETE accepted (202). Operation-Location: $op_loc"
    rm -f "$tmp_headers" "$tmp_body"

    # Poll the Operation-Location until terminal. Use a generous budget — agent
    # delete cascades through Foundry assistant/thread teardown and routinely
    # takes 30–120s. Total budget: 60 attempts × 5s = 5 minutes.
    local op_attempt=0 op_status op_resp op_code
    while (( op_attempt < 60 )); do
      op_attempt=$((op_attempt + 1))
      op_resp=$(curl -sS -w "\n%{http_code}" \
        -H "Authorization: Bearer $token" \
        -H "x-ms-client-tenant-id: ${TENANT_ID:-}" \
        "$op_loc" 2>/dev/null || true)
      op_code=$(echo "$op_resp" | tail -n 1)
      op_resp=$(echo "$op_resp" | sed '$d')

      if [[ "$op_code" == "404" ]]; then
        info "  Operation-Location 404 — treating agent '${aname}' as deleted."
        break
      fi

      if [[ "$op_code" != "200" && "$op_code" != "202" ]]; then
        warn "  Operation poll for '${aname}' returned HTTP $op_code: $(echo "$op_resp" | tr '\n' ' ' | head -c 500 | redact)"
        break
      fi

      op_status=$(echo "$op_resp" | jq -r '.status // .Status // empty' 2>/dev/null || echo "")
      case "${op_status,,}" in
        succeeded|completed)
          info "  Deleted data plane agent '${aname}' (LRO ${op_status})."
          break
          ;;
        failed|canceled|cancelled)
          warn "  Data plane agent '${aname}' delete reported terminal status '${op_status}': $(echo "$op_resp" | tr '\n' ' ' | head -c 500 | redact)"
          break
          ;;
        *)
          verbose "  LRO in progress (status='${op_status:-unknown}', attempt ${op_attempt}/60)"
          sleep 5
          ;;
      esac
    done

    if (( op_attempt >= 60 )); then
      warn "  Timed out polling Operation-Location for agent '${aname}' after 5 minutes."
    fi
  done <<< "$agent_names"

  # Poll until the data plane list is empty so Project deletion validation can pass.
  local poll_attempt=0
  while (( poll_attempt < 20 )); do
    poll_attempt=$((poll_attempt + 1))
    agents_response=$(curl -sS -w "\n%{http_code}" \
      -H "Authorization: Bearer $token" \
      -H "x-ms-client-tenant-id: ${TENANT_ID:-}" \
      "$agents_url" 2>/dev/null || true)
    agents_code=$(echo "$agents_response" | tail -n 1)
    agents_json=$(echo "$agents_response" | sed '$d')

    if [[ "$agents_code" == "404" ]]; then
      info "  Project agent endpoint returned 404; treating data plane agents as gone."
      return 0
    fi

    local remaining_count remaining_names remaining_list
    remaining_count=$(echo "$agents_json" | jq '(.value // .) | length' 2>/dev/null || echo "0")
    if [[ "$agents_code" == "200" && "$remaining_count" == "0" ]]; then
      info "  Data plane agents are gone for project $project_name."
      return 0
    fi

    remaining_names=$(echo "$agents_json" | jq -r '(.value // .)[]?.name // empty' 2>/dev/null | tr -d '\r' || true)
    remaining_list=$(echo "$remaining_names" | paste -sd ',' -)

    if [[ "$agents_code" != "200" ]]; then
      warn "  Agent list poll returned HTTP ${agents_code:-unknown}: $(echo "$agents_json" | tr '\n' ' ' | head -c 500 | redact)"
    fi
    info "  Waiting for data plane agent deletion to propagate (remaining=${remaining_count:-unknown}: ${remaining_list:-none}, attempt ${poll_attempt}/20)..."
    sleep 5
  done

  warn "  Timed out waiting for data plane agents to disappear for project $project_name. Remaining agent(s): ${remaining_list:-unknown}. Project deletion may still fail."
}

###############################################################################
# VNet pre-cleanup: strip subnet delegations & orphaned service-assoc links
#
# When a Container Apps (or similar) environment is deleted but its service
# association link on a subnet is not cleaned up, the VNet cannot be deleted.
#
# Strategy (in order):
#   1. Dissociate NSG from every subnet.
#   2. Remove delegations from subnets that have no orphaned service-
#      association links, then delete those subnets.
#   3. For subnets that DO have orphaned SALs (allowDelete=false):
#      a. Deploy a temporary Container Apps environment on the subnet to
#         "adopt" the orphaned legionservicelink.
#      b. Delete the temporary environment — which cleans up the SAL.
#      c. Delete the now-clean subnet.
###############################################################################
clean_vnet_subnets() {
  local vnet_id="$1"
  local vnet_name
  vnet_name=$(echo "$vnet_id" | grep -oP '(?i)virtualNetworks/\K[^/]+')

  info "  Pre-cleaning subnets on VNet: $vnet_name"

  # Determine VNet location (needed if we create a temp CAE).
  local vnet_location
  vnet_location=$(az network vnet show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$vnet_name" \
    --subscription "$SUBSCRIPTION_ID" \
    --query "location" -o tsv 2>/dev/null | tr -d '\r' || true)

  # Enumerate subnets.
  local subnets_json
  subnets_json=$(az network vnet subnet list \
    --resource-group "$RESOURCE_GROUP" \
    --vnet-name "$vnet_name" \
    --subscription "$SUBSCRIPTION_ID" \
    --output json 2>/dev/null || echo "[]")

  local subnet_count
  subnet_count=$(echo "$subnets_json" | jq 'length')
  if [[ "$subnet_count" -eq 0 ]]; then
    info "    No subnets found — nothing to clean."
    return 0
  fi

  # ---- Pass 1: dissociate NSG from each subnet ----
  local i=0
  while (( i < subnet_count )); do
    local sname nsg_id
    sname=$(echo "$subnets_json" | jq -r ".[$i].name")
    nsg_id=$(echo "$subnets_json" | jq -r ".[$i].networkSecurityGroup.id // empty")

    if [[ -n "$nsg_id" ]]; then
      info "    Removing NSG from subnet '$sname'..."
      az network vnet subnet update \
        --resource-group "$RESOURCE_GROUP" \
        --vnet-name "$vnet_name" \
        --name "$sname" \
        --subscription "$SUBSCRIPTION_ID" \
        --remove networkSecurityGroup \
        -o none 2>/dev/null || warn "    Could not remove NSG from '$sname'."
    fi
    i=$((i + 1))
  done

  # ---- Pass 2: classify subnets into clean vs orphaned ----
  # Re-fetch after NSG changes.
  subnets_json=$(az network vnet subnet list \
    --resource-group "$RESOURCE_GROUP" \
    --vnet-name "$vnet_name" \
    --subscription "$SUBSCRIPTION_ID" \
    --output json 2>/dev/null || echo "[]")
  subnet_count=$(echo "$subnets_json" | jq 'length')

  local -a orphaned_subnets=()
  i=0
  while (( i < subnet_count )); do
    local sname delegations_count sal_count
    sname=$(echo "$subnets_json" | jq -r ".[$i].name")
    delegations_count=$(echo "$subnets_json" | jq ".[$i].delegations | length")
    sal_count=$(echo "$subnets_json" | jq ".[$i].serviceAssociationLinks // [] | length")

    verbose "    Subnet '$sname': delegations=$delegations_count, serviceAssociationLinks=$sal_count"

    if (( sal_count > 0 )); then
      # Check if any link has allowDelete=false (truly orphaned).
      local blocked
      blocked=$(echo "$subnets_json" | jq ".[$i].serviceAssociationLinks // [] | map(select(.allowDelete == false)) | length")
      if (( blocked > 0 )); then
        warn "    Subnet '$sname' has orphaned service-association link(s) — needs special handling."
        orphaned_subnets+=("$sname")
        i=$((i + 1))
        continue
      fi
    fi

    # Clean subnet — remove delegations, then delete.
    if (( delegations_count > 0 )); then
      info "    Removing delegation(s) from subnet '$sname'..."
      az network vnet subnet update \
        --resource-group "$RESOURCE_GROUP" \
        --vnet-name "$vnet_name" \
        --name "$sname" \
        --subscription "$SUBSCRIPTION_ID" \
        --remove delegations 0 \
        -o none 2>/dev/null || true
    fi

    info "    Deleting subnet '$sname'..."
    az network vnet subnet delete \
      --resource-group "$RESOURCE_GROUP" \
      --vnet-name "$vnet_name" \
      --name "$sname" \
      --subscription "$SUBSCRIPTION_ID" \
      -o none 2>/dev/null && info "    Subnet '$sname' deleted." \
                          || warn "    Could not delete subnet '$sname'."

    i=$((i + 1))
  done

  # ---- Pass 3: handle orphaned subnets via temp Container Apps env ----
  if [[ ${#orphaned_subnets[@]} -eq 0 ]]; then
    return 0
  fi

  for sname in "${orphaned_subnets[@]}"; do
    local subnet_id
    subnet_id=$(az network vnet subnet show \
      --resource-group "$RESOURCE_GROUP" \
      --vnet-name "$vnet_name" \
      --name "$sname" \
      --subscription "$SUBSCRIPTION_ID" \
      --query "id" -o tsv 2>/dev/null | tr -d '\r' || true)

    if [[ -z "$subnet_id" ]]; then
      info "    Subnet '$sname' already gone — skipping."
      continue
    fi

    local temp_cae="temp-cae-cleanup-${RANDOM}"
    info "    Creating temporary Container Apps environment '$temp_cae' on subnet '$sname' to adopt orphaned link..."

    local cae_rc=0
    az containerapp env create \
      --name "$temp_cae" \
      --resource-group "$RESOURCE_GROUP" \
      --subscription "$SUBSCRIPTION_ID" \
      --location "${vnet_location:-eastus2}" \
      --infrastructure-subnet-resource-id "$subnet_id" \
      -o none 2>/dev/null || cae_rc=$?

    if [[ $cae_rc -ne 0 ]]; then
      warn "    Temporary CAE creation failed for subnet '$sname'. Orphaned link persists."
      continue
    fi

    info "    Deleting temporary Container Apps environment '$temp_cae'..."
    local cae_del_rc=0
    az containerapp env delete \
      --name "$temp_cae" \
      --resource-group "$RESOURCE_GROUP" \
      --subscription "$SUBSCRIPTION_ID" \
      --yes \
      -o none 2>/dev/null || cae_del_rc=$?

    if [[ $cae_del_rc -ne 0 ]]; then
      warn "    Temporary CAE deletion failed for '$temp_cae'. Manual cleanup required."
      continue
    fi

    info "    Deleting now-clean subnet '$sname'..."
    # May need a brief wait for ARM to propagate SAL removal.
    local del_attempt=0
    while (( del_attempt < 6 )); do
      local subdel_rc=0
      az network vnet subnet delete \
        --resource-group "$RESOURCE_GROUP" \
        --vnet-name "$vnet_name" \
        --name "$sname" \
        --subscription "$SUBSCRIPTION_ID" \
        -o none 2>/dev/null || subdel_rc=$?

      if [[ $subdel_rc -eq 0 ]]; then
        info "    Subnet '$sname' deleted."
        break
      fi

      del_attempt=$((del_attempt + 1))
      warn "    Subnet '$sname' still locked (attempt ${del_attempt}/6), retrying in 15s..."
      sleep 15
    done
  done
}

###############################################################################
# VNet deletion with pre-cleanup and RG-level fallback
#
# 1. Clean subnets (remove delegations / delete orphaned subnets).
# 2. Attempt VNet deletion.
# 3. If VNet deletion still fails (orphaned service-association link with
#    allowDelete=false blocks even subnet deletion), fall back to deleting the
#    entire resource group — which is the only ARM-level escape hatch for
#    orphaned links whose owning RP no longer exists.
###############################################################################
delete_vnets_with_cleanup() {
  info "=== Phase 22: Deleting Virtual Networks ==="

  if [[ ${#VNET_IDS[@]} -eq 0 ]]; then
    info "  No Virtual Networks to delete — skipping."
    return
  fi

  local vnet_failures=()
  for vnet_id in "${VNET_IDS[@]}"; do
    # Step 1: pre-clean subnets.
    clean_vnet_subnets "$vnet_id"

    # Step 2: try normal deletion.
    local del_rc=0
    delete_generic_resource "$vnet_id" || del_rc=$?

    if [[ $del_rc -ne 0 ]]; then
      vnet_failures+=("$vnet_id")
    fi
  done

  # Step 3: if any VNets remain, offer RG-level fallback.
  if [[ ${#vnet_failures[@]} -gt 0 ]]; then
    warn "  ${#vnet_failures[@]} VNet(s) could not be deleted (likely orphaned service-association links)."
    warn "  Orphaned links can only be removed by deleting the resource group."

    # Check whether VNets are the only resources left.
    local leftover
    leftover=$(list_all_resources)
    local leftover_count=0
    while IFS= read -r line; do
      [[ -n "$line" ]] && leftover_count=$((leftover_count + 1))
    done <<< "$leftover"

    # Only auto-fallback when the remaining resources are the VNets + their
    # companion NSGs (NRMS auto-creates them). Otherwise the user should decide.
    local vnet_nsg_count=$(( ${#vnet_failures[@]} + ${#NSG_IDS[@]} ))
    if (( leftover_count > 0 && leftover_count <= vnet_nsg_count )); then
      info "  Only VNet(s) and/or NSGs remain. Falling back to resource group deletion..."
      local rg_output rg_rc=0
      rg_output=$(az group delete --name "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION_ID" --yes 2>&1) || rg_rc=$?
      if [[ $rg_rc -ne 0 ]]; then
        log "ERROR Resource group deletion also failed: $RESOURCE_GROUP"
        echo "$rg_output" | redact >&2
        for vid in "${vnet_failures[@]}"; do
          FAILED_RESOURCES+=("$vid")
        done
      else
        info "  Resource group '$RESOURCE_GROUP' deleted (fallback)."
        # Mark a flag so the final resource-group cleanup knows the RG is already gone.
        RG_ALREADY_DELETED=true
      fi
    else
      warn "  Other resources remain — skipping automatic RG deletion."
      warn "  You can manually run: az group delete --name $RESOURCE_GROUP --subscription $SUBSCRIPTION_ID --yes"
      for vid in "${vnet_failures[@]}"; do
        FAILED_RESOURCES+=("$vid")
      done
    fi
  fi
}

###############################################################################
# Phase runner (takes array by nameref)
###############################################################################
run_phase() {
  local phase_num="$1"
  local phase_name="$2"
  local -n _phase_ids=$3

  info "=== Phase ${phase_num}: Deleting ${phase_name} ==="

  if [[ ${#_phase_ids[@]} -eq 0 ]]; then
    info "  No ${phase_name} to delete — skipping."
    return
  fi

  for id in "${_phase_ids[@]}"; do
    delete_resource "$id" || true
  done
}

###############################################################################
# Discovery phase — enumerate everything first
###############################################################################
declare -a DATAASSET_IDS=()
declare -a STORAGEASSET_IDS=()
declare -a AGENT_IDS=()
declare -a WORKFLOW_IDS=()
declare -a TOOL_IDS=()
declare -a MODEL_IDS=()
declare -a DATACONTAINER_IDS=()
declare -a PROJECT_IDS=()
declare -a CHATMODELDEPLOYMENT_IDS=()
declare -a WORKSPACE_PEC_PROXY_IDS=()
declare -a WORKSPACE_PEC_IDS=()
declare -a WORKSPACE_IDS=()
declare -a BOOKSHELF_PEC_PROXY_IDS=()
declare -a BOOKSHELF_PEC_IDS=()
declare -a BOOKSHELF_IDS=()
declare -a NODEPOOL_IDS=()
declare -a SUPERCOMPUTER_IDS=()
declare -a STORAGECONTAINER_IDS=()
declare -a STORAGE_IDS=()
declare -a STORAGE_ACCOUNT_IDS=()
declare -a UAMI_IDS=()
declare -a NSG_IDS=()
declare -a VNET_IDS=()
declare -a REMAINING_IDS=()
declare -a FAILED_RESOURCES=()
RG_ALREADY_DELETED=false

# Track IDs already assigned to a category so "remaining" excludes them.
declare -A KNOWN_IDS=()

mark_known() {
  local -n _mk_arr=$1
  for id in "${_mk_arr[@]}"; do
    KNOWN_IDS["$id"]=1
  done
}

discover_resources() {
  info "================================================================"
  info "Discovering resources in RG '$RESOURCE_GROUP'..."
  info "================================================================"
  echo ""

  # 1. DataAssets (child of DataContainers — must be deleted before DataContainers)
  info "Looking for DataAssets (Microsoft.Discovery/dataContainers/dataAssets)..."
  read_into_array DATAASSET_IDS < <(list_resources_by_type "Microsoft.Discovery/dataContainers/dataAssets")
  info "  Found ${#DATAASSET_IDS[@]} dataAsset(s)."
  for id in "${DATAASSET_IDS[@]}"; do info "    - $id"; done
  mark_known DATAASSET_IDS

  # 1b. StorageAssets (child of StorageContainers — must be deleted before StorageContainers)
  info "Looking for StorageAssets (Microsoft.Discovery/storageContainers/storageAssets)..."
  read_into_array STORAGEASSET_IDS < <(list_resources_by_type "Microsoft.Discovery/storageContainers/storageAssets")
  info "  Found ${#STORAGEASSET_IDS[@]} storageAsset(s)."
  for id in "${STORAGEASSET_IDS[@]}"; do info "    - $id"; done
  mark_known STORAGEASSET_IDS

  # 2. Agents (deleted after Projects so project cleanup can remove backreferences)
  info "Looking for Agents (Microsoft.Discovery/agents)..."
  read_into_array AGENT_IDS < <(list_resources_by_type "Microsoft.Discovery/agents")
  info "  Found ${#AGENT_IDS[@]} agent(s)."
  for id in "${AGENT_IDS[@]}"; do info "    - $id"; done
  mark_known AGENT_IDS

  # 3. Workflows
  info "Looking for Workflows (Microsoft.Discovery/workflows)..."
  read_into_array WORKFLOW_IDS < <(list_resources_by_type "Microsoft.Discovery/workflows")
  info "  Found ${#WORKFLOW_IDS[@]} workflow(s)."
  for id in "${WORKFLOW_IDS[@]}"; do info "    - $id"; done
  mark_known WORKFLOW_IDS

  # 4. Tools
  info "Looking for Tools (Microsoft.Discovery/tools)..."
  read_into_array TOOL_IDS < <(list_resources_by_type "Microsoft.Discovery/tools")
  info "  Found ${#TOOL_IDS[@]} tool(s)."
  for id in "${TOOL_IDS[@]}"; do info "    - $id"; done
  mark_known TOOL_IDS

  # 5. Models
  info "Looking for Models (Microsoft.Discovery/models)..."
  read_into_array MODEL_IDS < <(list_resources_by_type "Microsoft.Discovery/models")
  info "  Found ${#MODEL_IDS[@]} model(s)."
  for id in "${MODEL_IDS[@]}"; do info "    - $id"; done
  mark_known MODEL_IDS

  # 6. DataContainers (after DataAssets)
  info "Looking for DataContainers (Microsoft.Discovery/dataContainers)..."
  read_into_array DATACONTAINER_IDS < <(list_resources_by_type "Microsoft.Discovery/dataContainers")
  info "  Found ${#DATACONTAINER_IDS[@]} dataContainer(s)."
  for id in "${DATACONTAINER_IDS[@]}"; do info "    - $id"; done
  mark_known DATACONTAINER_IDS

  # 7. Projects (child of Workspace)
  info "Looking for Projects (Microsoft.Discovery/workspaces/projects)..."
  read_into_array PROJECT_IDS < <(list_resources_by_type "Microsoft.Discovery/workspaces/projects")
  info "  Found ${#PROJECT_IDS[@]} project(s)."
  for id in "${PROJECT_IDS[@]}"; do info "    - $id"; done
  mark_known PROJECT_IDS

  # 8. ChatModelDeployments (child of Workspace)
  info "Looking for ChatModelDeployments (Microsoft.Discovery/workspaces/chatModelDeployments)..."
  read_into_array CHATMODELDEPLOYMENT_IDS < <(list_resources_by_type "Microsoft.Discovery/workspaces/chatModelDeployments")
  info "  Found ${#CHATMODELDEPLOYMENT_IDS[@]} chatModelDeployment(s)."
  for id in "${CHATMODELDEPLOYMENT_IDS[@]}"; do info "    - $id"; done
  mark_known CHATMODELDEPLOYMENT_IDS

  # 8b. Workspace Private Endpoint Connection Proxies
  info "Looking for Workspace PrivateEndpointConnectionProxies (Microsoft.Discovery/workspaces/privateEndpointConnectionProxies)..."
  read_into_array WORKSPACE_PEC_PROXY_IDS < <(list_resources_by_type "Microsoft.Discovery/workspaces/privateEndpointConnectionProxies")
  info "  Found ${#WORKSPACE_PEC_PROXY_IDS[@]} workspace privateEndpointConnectionProxy resource(s)."
  for id in "${WORKSPACE_PEC_PROXY_IDS[@]}"; do info "    - $id"; done
  mark_known WORKSPACE_PEC_PROXY_IDS

  # 8c. Workspace Private Endpoint Connections
  info "Looking for Workspace PrivateEndpointConnections (Microsoft.Discovery/workspaces/privateEndpointConnections)..."
  read_into_array WORKSPACE_PEC_IDS < <(list_resources_by_type "Microsoft.Discovery/workspaces/privateEndpointConnections")
  info "  Found ${#WORKSPACE_PEC_IDS[@]} workspace privateEndpointConnection resource(s)."
  for id in "${WORKSPACE_PEC_IDS[@]}"; do info "    - $id"; done
  mark_known WORKSPACE_PEC_IDS

  # 9. Workspaces
  info "Looking for Workspaces (Microsoft.Discovery/workspaces)..."
  read_into_array WORKSPACE_IDS < <(list_resources_by_type "Microsoft.Discovery/workspaces")
  info "  Found ${#WORKSPACE_IDS[@]} workspace(s)."
  for id in "${WORKSPACE_IDS[@]}"; do info "    - $id"; done
  mark_known WORKSPACE_IDS

  # 9b. Bookshelf Private Endpoint Connection Proxies
  info "Looking for Bookshelf PrivateEndpointConnectionProxies (Microsoft.Discovery/bookshelves/privateEndpointConnectionProxies)..."
  read_into_array BOOKSHELF_PEC_PROXY_IDS < <(list_resources_by_type "Microsoft.Discovery/bookshelves/privateEndpointConnectionProxies")
  info "  Found ${#BOOKSHELF_PEC_PROXY_IDS[@]} bookshelf privateEndpointConnectionProxy resource(s)."
  for id in "${BOOKSHELF_PEC_PROXY_IDS[@]}"; do info "    - $id"; done
  mark_known BOOKSHELF_PEC_PROXY_IDS

  # 9c. Bookshelf Private Endpoint Connections
  info "Looking for Bookshelf PrivateEndpointConnections (Microsoft.Discovery/bookshelves/privateEndpointConnections)..."
  read_into_array BOOKSHELF_PEC_IDS < <(list_resources_by_type "Microsoft.Discovery/bookshelves/privateEndpointConnections")
  info "  Found ${#BOOKSHELF_PEC_IDS[@]} bookshelf privateEndpointConnection resource(s)."
  for id in "${BOOKSHELF_PEC_IDS[@]}"; do info "    - $id"; done
  mark_known BOOKSHELF_PEC_IDS

  # 9d. Bookshelves
  info "Looking for Bookshelves (Microsoft.Discovery/bookshelves)..."
  read_into_array BOOKSHELF_IDS < <(list_resources_by_type "Microsoft.Discovery/bookshelves")
  info "  Found ${#BOOKSHELF_IDS[@]} bookshelf resource(s)."
  for id in "${BOOKSHELF_IDS[@]}"; do info "    - $id"; done
  mark_known BOOKSHELF_IDS

  # 10. NodePools (child of Supercomputer)
  info "Looking for NodePools (Microsoft.Discovery/supercomputers/nodePools)..."
  read_into_array NODEPOOL_IDS < <(list_resources_by_type "Microsoft.Discovery/supercomputers/nodePools")
  info "  Found ${#NODEPOOL_IDS[@]} nodepool(s)."
  for id in "${NODEPOOL_IDS[@]}"; do info "    - $id"; done
  mark_known NODEPOOL_IDS

  # 11. Supercomputers
  info "Looking for Supercomputers (Microsoft.Discovery/supercomputers)..."
  read_into_array SUPERCOMPUTER_IDS < <(list_resources_by_type "Microsoft.Discovery/supercomputers")
  info "  Found ${#SUPERCOMPUTER_IDS[@]} supercomputer(s)."
  for id in "${SUPERCOMPUTER_IDS[@]}"; do info "    - $id"; done
  mark_known SUPERCOMPUTER_IDS

  # 12. StorageContainers
  info "Looking for StorageContainers (Microsoft.Discovery/storageContainers)..."
  read_into_array STORAGECONTAINER_IDS < <(list_resources_by_type "Microsoft.Discovery/storageContainers")
  info "  Found ${#STORAGECONTAINER_IDS[@]} storage container(s)."
  for id in "${STORAGECONTAINER_IDS[@]}"; do info "    - $id"; done
  mark_known STORAGECONTAINER_IDS

  # 12b. Storages
  info "Looking for Storages (Microsoft.Discovery/storages)..."
  read_into_array STORAGE_IDS < <(list_resources_by_type "Microsoft.Discovery/storages")
  info "  Found ${#STORAGE_IDS[@]} storage resource(s)."
  for id in "${STORAGE_IDS[@]}"; do info "    - $id"; done
  mark_known STORAGE_IDS

  # 13. Azure Blob Storage Accounts
  info "Looking for Storage Accounts (Microsoft.Storage/storageAccounts)..."
  read_into_array STORAGE_ACCOUNT_IDS < <(list_resources_by_type "Microsoft.Storage/storageAccounts")
  info "  Found ${#STORAGE_ACCOUNT_IDS[@]} storage account(s)."
  for id in "${STORAGE_ACCOUNT_IDS[@]}"; do info "    - $id"; done
  mark_known STORAGE_ACCOUNT_IDS

  # 14. User-Assigned Managed Identities
  info "Looking for Managed Identities (Microsoft.ManagedIdentity/userAssignedIdentities)..."
  read_into_array UAMI_IDS < <(list_resources_by_type "Microsoft.ManagedIdentity/userAssignedIdentities")
  info "  Found ${#UAMI_IDS[@]} UAMI(s)."
  for id in "${UAMI_IDS[@]}"; do info "    - $id"; done
  mark_known UAMI_IDS

  # 15. Virtual Networks
  info "Looking for Virtual Networks (Microsoft.Network/virtualNetworks)..."
  read_into_array VNET_IDS < <(list_resources_by_type "Microsoft.Network/virtualNetworks")
  info "  Found ${#VNET_IDS[@]} VNet(s)."
  for id in "${VNET_IDS[@]}"; do info "    - $id"; done
  mark_known VNET_IDS

  # 16. Everything else not already categorised
  info "Looking for any remaining resources..."
  REMAINING_IDS=()
  local line
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ -z "${KNOWN_IDS[$line]+x}" ]]; then
      REMAINING_IDS+=("$line")
    fi
  done < <(list_all_resources)
  info "  Found ${#REMAINING_IDS[@]} remaining resource(s)."
  for id in "${REMAINING_IDS[@]}"; do info "    - $id"; done

  echo ""
}

###############################################################################
# Summary
###############################################################################
print_summary() {
  local total=$(( ${#DATAASSET_IDS[@]} + ${#STORAGEASSET_IDS[@]} + ${#AGENT_IDS[@]} + ${#WORKFLOW_IDS[@]} + ${#TOOL_IDS[@]} \
    + ${#MODEL_IDS[@]} + ${#DATACONTAINER_IDS[@]} + ${#PROJECT_IDS[@]} + ${#CHATMODELDEPLOYMENT_IDS[@]} \
    + ${#WORKSPACE_PEC_PROXY_IDS[@]} + ${#WORKSPACE_PEC_IDS[@]} + ${#WORKSPACE_IDS[@]} \
    + ${#BOOKSHELF_PEC_PROXY_IDS[@]} + ${#BOOKSHELF_PEC_IDS[@]} + ${#BOOKSHELF_IDS[@]} \
    + ${#NODEPOOL_IDS[@]} + ${#SUPERCOMPUTER_IDS[@]} + ${#STORAGECONTAINER_IDS[@]} + ${#STORAGE_IDS[@]} \
    + ${#STORAGE_ACCOUNT_IDS[@]} + ${#UAMI_IDS[@]} + ${#VNET_IDS[@]} + ${#REMAINING_IDS[@]} ))

  echo ""
  echo "========================================================================"
  echo "  Deletion Plan (api-version ${API_VERSION})"
  echo "========================================================================"
  echo "  Subscription:    $SUBSCRIPTION_ID"
  echo "  Resource Group:  $RESOURCE_GROUP"
  echo ""
  echo "  Phase  1: DataAssets (Discovery) ............. ${#DATAASSET_IDS[@]}"
  echo "  Phase  2: StorageAssets (Discovery) .......... ${#STORAGEASSET_IDS[@]}"
  echo "  Phase  3: Data Plane Agents (per project) .... (cleaned before project deletion)"
  echo "  Phase  4: Projects (Discovery) ............... ${#PROJECT_IDS[@]}"
  echo "  Phase  5: Agents (Discovery, ARM) ............ ${#AGENT_IDS[@]}  (best-effort link cleanup + retry later)"
  echo "  Phase  6: ChatModelDeployments (Discovery) ... ${#CHATMODELDEPLOYMENT_IDS[@]}"
  echo "  Phase  7: Tools (Discovery) .................. ${#TOOL_IDS[@]}  (PATCH + deferred retry)"
  echo "  Phase  8: Workflows (Discovery) .............. ${#WORKFLOW_IDS[@]}"
  echo "  Phase  9: Models (Discovery) ................. ${#MODEL_IDS[@]}"
  echo "  Phase 10: DataContainers (Discovery) ......... ${#DATACONTAINER_IDS[@]}"
  echo "  Phase 11: StorageContainers (Discovery) ...... ${#STORAGECONTAINER_IDS[@]}"
  echo "  Phase 12: Workspace PECP/PEC (Discovery) ..... ${#WORKSPACE_PEC_PROXY_IDS[@]}/${#WORKSPACE_PEC_IDS[@]}"
  echo "  Phase 13: Bookshelf PECP/PEC (Discovery) ..... ${#BOOKSHELF_PEC_PROXY_IDS[@]}/${#BOOKSHELF_PEC_IDS[@]}"
  echo "  Phase 14: Unlink Workspaces .................. ${#WORKSPACE_IDS[@]}"
  echo "  Phase 15: Workspaces (Discovery) ............. ${#WORKSPACE_IDS[@]}"
  echo "  Phase 16: Bookshelves (Discovery) ............ ${#BOOKSHELF_IDS[@]}"
  echo "  Phase 17: NodePools (Discovery) .............. ${#NODEPOOL_IDS[@]}"
  echo "  Phase 18: Supercomputers (Discovery) ......... ${#SUPERCOMPUTER_IDS[@]}"
  echo "  Phase 19: Storages (Discovery) ............... ${#STORAGE_IDS[@]}"
  echo "  Phase 20: Storage Accounts ................... ${#STORAGE_ACCOUNT_IDS[@]}"
  echo "  Phase 21: User-Assigned Managed Identities ... ${#UAMI_IDS[@]}"
  echo "  Phase 22: Virtual Networks (+ subnet clean) .. ${#VNET_IDS[@]}"
  echo "  Phase 23: Remaining .......................... ${#REMAINING_IDS[@]}"
  echo ""
  echo "  Total: ${total} resource(s) (+ data plane agents cleaned per project)"
  echo "========================================================================"
}

###############################################################################
# Main
###############################################################################
main() {
  parse_args "$@"
  check_prereqs

  info "Subscription  : $SUBSCRIPTION_ID"
  info "Resource Group: $RESOURCE_GROUP"
  info "API Version   : $API_VERSION"
  info "DP API Version: $DP_API_VERSION (data-plane agents)"
  [[ "$DRY_RUN"  == true ]] && info "Mode          : DRY RUN (no deletions will occur)"
  [[ "$VERBOSE"  == true ]] && info "Verbose       : ON"
  [[ "$FORCE"    == true ]] && info "Force         : ON (skipping confirmation)"
  [[ "$CONTINUE_ON_ERROR" == true ]] && info "Continue      : ON (will not abort on individual failures)"
  echo ""

  # Set subscription context (assumes user has already run az login).
  az account set --subscription "$SUBSCRIPTION_ID"
  info "Subscription set to: $SUBSCRIPTION_ID"
  TENANT_ID=$(az account show --subscription "$SUBSCRIPTION_ID" --query tenantId -o tsv 2>/dev/null | tr -d '\r' || true)
  [[ -n "$TENANT_ID" ]] && info "Tenant       : $TENANT_ID"
  echo ""

  # --- Discover all resources first ---
  discover_resources

  # --- Print summary ---
  print_summary

  # --- Dry-run exits here ---
  if [[ "$DRY_RUN" == true ]]; then
    echo ""
    info "Dry-run complete. No resources were deleted."
    exit 0
  fi

  # --- Confirmation prompt (unless --force) ---
  if [[ "$FORCE" != true ]]; then
    echo ""
    echo "========================================================================"
    echo "  WARNING: This will DELETE ALL the resources listed above in"
    echo "           resource group '$RESOURCE_GROUP'"
    echo "           under subscription '$SUBSCRIPTION_ID'."
    echo ""
    echo "  Individual failures will be collected so later cleanup phases"
    echo "  and the resource-group fallback can still run."
    echo "========================================================================"
    read -r -p "Type 'yes' to confirm and begin deletion: " confirm
    if [[ "$confirm" != "yes" ]]; then
      info "Aborted by user."
      exit 0
    fi
  fi

  echo ""

  # --- Execute deletion phases in strict order ---
  #
  # Dependency chain that dictates phase order:
  #   Data plane agents → must be absent before V2 Project deletion validation passes.
  #   Projects          → delink ARM Agents, Workflows, DataContainers, and StorageContainers.
  #   ARM Agents        → delete after Projects, then Tools/ChatModelDeployments can be deleted.
  #   Child resources   → private endpoint child resources before parent Workspaces/Bookshelves.
  #   Workspaces        → patch supercomputerIds to [] before deletion.
  #   Storages/SCs      → delete after their linked projects/workspaces are gone or unlinked.
  #
  # All phases run with CONTINUE_ON_ERROR=true so the script always reaches
  # the nuclear fallback (az group delete) if individual deletions fail.
  local saved_continue_on_error="$CONTINUE_ON_ERROR"
  CONTINUE_ON_ERROR=true

  # Phase 1: DataAssets (child of DataContainers — must go first)
  run_phase 1  "DataAssets"                  DATAASSET_IDS
  echo ""

  # Phase 2: StorageAssets (child of StorageContainers — must go before StorageContainers)
  run_phase 2  "StorageAssets"               STORAGEASSET_IDS
  echo ""

  # Phase 3: Data plane agents from every project.
  # These agents are NOT ARM resources so az resource list won't find them.
  # They block BOTH Tool deletion (via LinkedAgentIds referencing data-plane URLs)
  # AND Project deletion (V2 ProjectValidator checks for data plane agents).
  info "=== Phase 3: Cleaning data plane agents from Projects ==="
  if [[ ${#PROJECT_IDS[@]} -eq 0 ]]; then
    info "  No projects — skipping data plane agent cleanup."
  else
    for id in "${PROJECT_IDS[@]}"; do
      cleanup_dataplane_agents_for_project "$id" || true
    done
  fi
  echo ""

  # Phase 4: Projects. Project deletion delinks referenced ARM Agents,
  # Workflows, DataContainers, and V2 StorageContainers in backend activities.
  run_phase 4  "Projects"                   PROJECT_IDS
  echo ""

  # Phase 5: ARM Agents. Project deletion should have removed LinkedProjectIds.
  # Best-effort link cleanup handles stale/cyclic Agent metadata before deletion.
  info "=== Phase 5: Deleting Agents (ARM) ==="
  declare -a DEFERRED_AGENT_IDS=()
  if [[ ${#AGENT_IDS[@]} -eq 0 ]]; then
    info "  No Agents to delete — skipping."
  else
    for id in "${AGENT_IDS[@]}"; do
      clear_agent_blocking_links "$id" || true
      if ! delete_resource "$id"; then
        info "  Agent deletion deferred — will retry after tools/workspaces cleanup: $id"
        DEFERRED_AGENT_IDS+=("$id")
      fi
    done
  fi
  echo ""

  # Phase 6: ChatModelDeployments. Data plane agents are gone, so LinkedAgentIds
  # validation should no longer block deletion.
  run_phase 6  "ChatModelDeployments"       CHATMODELDEPLOYMENT_IDS
  echo ""

  # Phase 7: Tools. Clear InternalMetadata.LinkedAgentIds before deletion.
  info "=== Phase 7: Deleting Tools ==="
  declare -a DEFERRED_TOOL_IDS=()
  if [[ ${#TOOL_IDS[@]} -eq 0 ]]; then
    info "  No Tools to delete — skipping."
  else
    for id in "${TOOL_IDS[@]}"; do
      # Clear LinkedAgentIds via ARM PATCH before attempting DELETE.
      clear_tool_linked_agents "$id" || true

      # Attempt deletion; on failure defer instead of aborting.
      if ! delete_resource "$id"; then
        info "  Tool deletion deferred — will retry after workspace cleanup: $id"
        DEFERRED_TOOL_IDS+=("$id")
      fi
    done
  fi
  echo ""
  run_phase 8  "Workflows"                  WORKFLOW_IDS
  echo ""
  run_phase 9  "Models"                     MODEL_IDS
  echo ""
  run_phase 10 "DataContainers"             DATACONTAINER_IDS
  echo ""

  run_phase 11 "StorageContainers"          STORAGECONTAINER_IDS
  echo ""

  # Private endpoint child resources before parent Workspaces/Bookshelves.
  run_phase 12 "Workspace PrivateEndpointConnectionProxies" WORKSPACE_PEC_PROXY_IDS
  echo ""
  run_phase 12 "Workspace PrivateEndpointConnections" WORKSPACE_PEC_IDS
  echo ""
  run_phase 13 "Bookshelf PrivateEndpointConnectionProxies" BOOKSHELF_PEC_PROXY_IDS
  echo ""
  run_phase 13 "Bookshelf PrivateEndpointConnections" BOOKSHELF_PEC_IDS
  echo ""

  # --- Phase 14: Unlink workspaces from supercomputers ---
  info "=== Phase 14: Unlinking Workspaces from Supercomputers ==="
  if [[ ${#WORKSPACE_IDS[@]} -eq 0 ]]; then
    info "  No workspaces to unlink — skipping."
  else
    for id in "${WORKSPACE_IDS[@]}"; do
      unlink_workspace_dependencies "$id" || true
    done
  fi
  echo ""

  run_phase 15 "Workspaces"                 WORKSPACE_IDS
  echo ""

  run_phase 16 "Bookshelves"                BOOKSHELF_IDS
  echo ""

  # Retry deferred Agents and Tools after the major parents are gone.
  if [[ ${#DEFERRED_AGENT_IDS[@]} -gt 0 ]]; then
    info "=== Phase 5b: Retrying ${#DEFERRED_AGENT_IDS[@]} deferred Agent(s) ==="
    local -a NEW_FAILED=()
    for fid in "${FAILED_RESOURCES[@]}"; do
      local is_deferred=false
      for did in "${DEFERRED_AGENT_IDS[@]}"; do
        [[ "$fid" == "$did" ]] && is_deferred=true && break
      done
      [[ "$is_deferred" == false ]] && NEW_FAILED+=("$fid")
    done
    FAILED_RESOURCES=("${NEW_FAILED[@]}")

    for id in "${DEFERRED_AGENT_IDS[@]}"; do
      clear_agent_blocking_links "$id" || true
      delete_resource "$id" || true
    done
  fi
  echo ""

  if [[ ${#DEFERRED_TOOL_IDS[@]} -gt 0 ]]; then
    info "=== Phase 7b: Retrying ${#DEFERRED_TOOL_IDS[@]} deferred Tool(s) ==="
    # Remove deferred tools from FAILED_RESOURCES so they get a fresh chance.
    local -a NEW_FAILED=()
    for fid in "${FAILED_RESOURCES[@]}"; do
      local is_deferred=false
      for did in "${DEFERRED_TOOL_IDS[@]}"; do
        [[ "$fid" == "$did" ]] && is_deferred=true && break
      done
      [[ "$is_deferred" == false ]] && NEW_FAILED+=("$fid")
    done
    FAILED_RESOURCES=("${NEW_FAILED[@]}")

    for id in "${DEFERRED_TOOL_IDS[@]}"; do
      clear_tool_linked_agents "$id" || true
      delete_resource "$id" || true
    done
  fi
  echo ""

  run_phase 17 "NodePools"                  NODEPOOL_IDS
  echo ""
  run_phase 18 "Supercomputers"             SUPERCOMPUTER_IDS
  echo ""
  run_phase 19 "Storages"                   STORAGE_IDS
  echo ""
  run_phase 20 "Storage Accounts"           STORAGE_ACCOUNT_IDS
  echo ""
  run_phase 21 "User-Assigned Managed Identities" UAMI_IDS
  echo ""
  delete_vnets_with_cleanup
  echo ""
  run_phase 23 "Remaining resources"        REMAINING_IDS

  echo ""

  # Restore CONTINUE_ON_ERROR.
  CONTINUE_ON_ERROR="$saved_continue_on_error"

  # --- Report failures and nuclear fallback ---
  if [[ ${#FAILED_RESOURCES[@]} -gt 0 ]]; then
    echo "========================================================================"
    echo "  ${#FAILED_RESOURCES[@]} resource(s) FAILED to delete individually:"
    echo "========================================================================"
    for fid in "${FAILED_RESOURCES[@]}"; do
      echo "    - $fid"
    done
    echo "========================================================================"
    echo ""
    info "=== Nuclear fallback: deleting entire resource group ==="
    info "  Individual resource deletions failed. Falling back to"
    info "  'az group delete' which deletes the resource group and ALL"
    info "  its contents via ARM's bulk-deletion orchestration."
    info ""
    info "  Deleting resource group '$RESOURCE_GROUP'..."

    local rg_output rg_rc=0
    rg_output=$(az group delete --name "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION_ID" --yes --no-wait 2>&1) || rg_rc=$?
    if [[ $rg_rc -ne 0 ]]; then
      log "ERROR 'az group delete' also failed:"
      echo "$rg_output" | redact >&2
      echo ""
      warn "Manual cleanup required. Try:"
      warn "  az group delete -n $RESOURCE_GROUP --subscription $SUBSCRIPTION_ID --yes"
      exit 1
    fi

    info "  Resource group deletion initiated (--no-wait). ARM will continue"
    info "  deleting in the background. Check the Azure Portal for status."
    info "=== Done (with fallback). ==="
    exit 0
  fi

  # --- Phase 24: Delete resource group if empty ---
  if [[ "${RG_ALREADY_DELETED:-false}" == true ]]; then
    info "=== Phase 24: Resource group already deleted (VNet fallback) ==="
  else
    info "=== Phase 24: Checking if resource group is empty ==="
    local leftover
    leftover=$(list_all_resources)
    if [[ -z "$leftover" ]]; then
      info "  Resource group '$RESOURCE_GROUP' is empty. Deleting it..."
      local rg_output rg_rc=0
      rg_output=$(az group delete --name "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION_ID" --yes 2>&1) || rg_rc=$?
      if [[ $rg_rc -ne 0 ]]; then
        log "ERROR Failed to delete resource group: $RESOURCE_GROUP"
        echo "$rg_output" | redact >&2
        exit 1
      fi
      info "  Resource group '$RESOURCE_GROUP' deleted."
    else
      warn "  Resource group is NOT empty — skipping resource group deletion."
      warn "  Remaining resources:"
      while IFS= read -r line; do
        [[ -n "$line" ]] && warn "    - $line"
      done <<< "$leftover"
    fi
  fi

  info "=== All done. ==="
}

main "$@"
