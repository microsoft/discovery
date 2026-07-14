# shellcheck shell=bash
# -----------------------------------------------------------------------------
# 09-network-security-perimeter.sh
#
# Verify prerequisites for deploying network-hardened (NSP-joined) Discovery
# workspaces. The Terraform module in this directory currently deploys
# standard VNet-injected workspaces (no NSP), so this module is OPT-IN and
# self-skips unless PREFLIGHT_CHECK_NSP=1 is set. If you extend the Terraform
# module to stamp `networkIsolation: "true"` on the workspace, enable this.
#
# Four sub-checks (mirroring the toolbox `netSec.*` checks in
# ../discovery-toolbox v1.1.67):
#   a. AIFSPInfrastructure service principal exists in the tenant
#   b. A custom role with joinPerimeterRule/action exists in the subscription
#   c. That role is assigned to the AIFSPInfrastructure SP
#   d. The AIFSPInfrastructure SP has Reader at subscription scope
#
# Constants sourced from the toolbox bundle:
#   AIFSPInfrastructure app id : 92c174ac-8e41-4815-a1b7-d81b19ab03ce
#   Required role action       : Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action
#
# NOTE: sub-check (a) requires Graph read (Directory.Read.All /
# Application.Read.All). Non-admin accounts see a 403 and get a WARN instead
# of a FAIL, matching toolbox behaviour.
# -----------------------------------------------------------------------------

info "9. Network Security Perimeter prerequisites"

if [[ "${PREFLIGHT_CHECK_NSP:-0}" != "1" ]]; then
  info "  (skipped -- set PREFLIGHT_CHECK_NSP=1 to enable; only needed for network-hardened workspaces)"
  return 0 2>/dev/null || true
fi

_pf09_sp_app_id="92c174ac-8e41-4815-a1b7-d81b19ab03ce"
_pf09_sp_name="AIFSPInfrastructure"
_pf09_role_action="Microsoft.Network/networkSecurityPerimeters/joinPerimeterRule/action"

# ---- (a) AIFSPInfrastructure service principal exists ----------------------
_pf09_sp_json=$(az ad sp show --id "$_pf09_sp_app_id" 2>/dev/null || true)
_pf09_sp_object_id=""
if [[ -n "$_pf09_sp_json" && "$_pf09_sp_json" != "null" ]]; then
  _pf09_sp_object_id=$(echo "$_pf09_sp_json" | jq -r '.id // .objectId // empty')
fi

if [[ -n "$_pf09_sp_object_id" ]]; then
  pass "  ${_pf09_sp_name} SP exists (objectId ${_pf09_sp_object_id})"
else
  # Distinguish "not present" from "no permission to look it up".
  _pf09_err=$(az ad sp show --id "$_pf09_sp_app_id" 2>&1 >/dev/null || true)
  if echo "$_pf09_err" | grep -qiE 'insufficient|forbidden|403|Authorization_RequestDenied'; then
    warn "  cannot verify ${_pf09_sp_name} SP -- signed-in account lacks Graph read (Directory.Read.All). Ask a tenant admin to run 'az ad sp create --id ${_pf09_sp_app_id}' if missing."
  else
    fail "  ${_pf09_sp_name} SP (appId ${_pf09_sp_app_id}) not found. Run: az ad sp create --id ${_pf09_sp_app_id}"
  fi
fi

# ---- (b) Custom role with joinPerimeterRule/action exists ------------------
_pf09_role_json=$(az role definition list --scope "/subscriptions/${SUB_ID}" --custom-role-only true -o json 2>/dev/null || true)
_pf09_role_name=""
_pf09_role_id=""
if [[ -n "$_pf09_role_json" && "$_pf09_role_json" != "[]" && "$_pf09_role_json" != "null" ]]; then
  _pf09_role_hit=$(echo "$_pf09_role_json" | jq -c --arg act "$_pf09_role_action" '
    map(select(
      (.permissions // []) | any(
        ((.actions // []) + (.dataActions // []))
        | map(ascii_downcase)
        | any(. == ($act | ascii_downcase))
      )
    )) | .[0] // empty')
  if [[ -n "$_pf09_role_hit" ]]; then
    _pf09_role_name=$(echo "$_pf09_role_hit" | jq -r '.roleName')
    _pf09_role_id=$(echo   "$_pf09_role_hit" | jq -r '.name // .id')
  fi
fi

if [[ -n "$_pf09_role_name" ]]; then
  pass "  NSP Perimeter Joiner custom role exists ('${_pf09_role_name}')"
else
  fail "  no custom role grants '${_pf09_role_action}' in the subscription. Create one before assigning to ${_pf09_sp_name}."
fi

# ---- (c) That role is assigned to the AIFSPInfrastructure SP ---------------
if [[ -n "$_pf09_role_name" ]]; then
  if [[ -n "$_pf09_sp_object_id" ]]; then
    _pf09_assign_count=$(az role assignment list \
        --scope "/subscriptions/${SUB_ID}" \
        --assignee-object-id "$_pf09_sp_object_id" \
        --role "$_pf09_role_name" \
        --query 'length(@)' -o tsv 2>/dev/null || echo 0)
    if [[ "${_pf09_assign_count:-0}" -ge 1 ]]; then
      pass "  '${_pf09_role_name}' is assigned to ${_pf09_sp_name} at subscription scope"
    else
      fail "  '${_pf09_role_name}' is NOT assigned to ${_pf09_sp_name}. Run: az role assignment create --assignee-object-id ${_pf09_sp_object_id} --assignee-principal-type ServicePrincipal --role '${_pf09_role_name}' --scope /subscriptions/${SUB_ID}"
    fi
  else
    # SP lookup failed (403 / not present) -- fall back to any-assignment
    # heuristic used by the toolbox: this role only grants an action Discovery
    # cares about, so any assignment is effectively the Discovery SP.
    _pf09_any_count=$(az role assignment list \
        --scope "/subscriptions/${SUB_ID}" \
        --role "$_pf09_role_name" \
        --query 'length(@)' -o tsv 2>/dev/null || echo 0)
    if [[ "${_pf09_any_count:-0}" -ge 1 ]]; then
      warn "  '${_pf09_role_name}' has ${_pf09_any_count} assignment(s) (cannot confirm assignee without Graph read; presumed correct)"
    else
      fail "  '${_pf09_role_name}' has zero assignments at subscription scope"
    fi
  fi
fi

# ---- (d) AIFSPInfrastructure has Reader at subscription --------------------
if [[ -n "$_pf09_sp_object_id" ]]; then
  _pf09_reader_count=$(az role assignment list \
      --scope "/subscriptions/${SUB_ID}" \
      --assignee-object-id "$_pf09_sp_object_id" \
      --role Reader \
      --query 'length(@)' -o tsv 2>/dev/null || echo 0)
  if [[ "${_pf09_reader_count:-0}" -ge 1 ]]; then
    pass "  Reader is assigned to ${_pf09_sp_name} at subscription scope"
  else
    fail "  Reader is NOT assigned to ${_pf09_sp_name}. Run: az role assignment create --assignee-object-id ${_pf09_sp_object_id} --assignee-principal-type ServicePrincipal --role Reader --scope /subscriptions/${SUB_ID}"
  fi
else
  warn "  skipping Reader check -- ${_pf09_sp_name} object id not available"
fi

unset _pf09_sp_app_id _pf09_sp_name _pf09_role_action _pf09_sp_json _pf09_sp_object_id \
      _pf09_err _pf09_role_json _pf09_role_name _pf09_role_id _pf09_role_hit \
      _pf09_assign_count _pf09_any_count _pf09_reader_count
