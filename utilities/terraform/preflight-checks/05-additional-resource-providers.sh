# shellcheck shell=bash
# -----------------------------------------------------------------------------
# 05-additional-resource-providers.sh
#
# Check that every non-Discovery resource provider consumed by the Discovery
# platform is registered on the target subscription. `terraform apply` will
# fail deep in the middle of the graph if any of these are Unregistered, and
# the failure surface is confusing (opaque ARM 400s from AzAPI).
#
# `Microsoft.Discovery` itself is intentionally NOT checked here -- that's
# check 1 in `preflight.sh`. Removing this file only loses coverage on the
# 24 dependency RPs, not on the core Discovery RP.
#
# Provenance: mirrors the 25-RP registry embedded in
# `../discovery-toolbox` (id `rp.*` in the toolbox category
# `resourceProviders`). Namespaces reflect toolbox v1.1.67.
# -----------------------------------------------------------------------------

info "5. Additional resource providers (24 dependencies)"

_pf05_namespaces=(
  Microsoft.AlertsManagement
  Microsoft.App
  Microsoft.Authorization
  Microsoft.Bing
  Microsoft.CognitiveServices
  Microsoft.Compute
  Microsoft.ContainerInstance
  Microsoft.ContainerRegistry
  Microsoft.ContainerService
  Microsoft.DocumentDB
  Microsoft.Features
  Microsoft.Insights
  Microsoft.KeyVault
  Microsoft.MachineLearningServices
  Microsoft.ManagedIdentity
  Microsoft.NetApp
  Microsoft.Network
  Microsoft.OperationalInsights
  Microsoft.ResourceGraph
  Microsoft.Resources
  Microsoft.Search
  Microsoft.Sql
  Microsoft.Storage
  Microsoft.Web
)

# Single ARM call for the whole subscription -- cheaper than 24 round trips.
_pf05_all=$(az provider list --query "[].{ns:namespace, state:registrationState}" -o json 2>/dev/null)

if [[ -z "$_pf05_all" || "$_pf05_all" == "null" ]]; then
  warn "  could not query subscription providers (az provider list failed) -- skipping"
else
  _pf05_unregistered=()
  _pf05_registering=()
  for ns in "${_pf05_namespaces[@]}"; do
    state=$(echo "$_pf05_all" | jq -r --arg ns "$ns" '.[] | select(.ns == $ns) | .state')
    case "$state" in
      Registered)   ;;                              # silent success -- avoid 24 PASS lines
      Registering)  _pf05_registering+=("$ns") ;;
      "")           _pf05_unregistered+=("${ns} (not visible)") ;;
      *)            _pf05_unregistered+=("${ns} (${state})") ;;
    esac
  done

  _pf05_ok=$(( ${#_pf05_namespaces[@]} - ${#_pf05_unregistered[@]} - ${#_pf05_registering[@]} ))
  pass "  ${_pf05_ok}/${#_pf05_namespaces[@]} dependency RPs are Registered"

  if (( ${#_pf05_registering[@]} > 0 )); then
    warn "  ${#_pf05_registering[@]} RP(s) still Registering: ${_pf05_registering[*]} -- wait a minute and re-run"
  fi

  if (( ${#_pf05_unregistered[@]} > 0 )); then
    fail "  ${#_pf05_unregistered[@]} RP(s) not registered: ${_pf05_unregistered[*]}"
    printf "         to fix, run:\n"
    for entry in "${_pf05_unregistered[@]}"; do
      # Strip parenthetical state annotation to get bare namespace.
      ns=${entry%% *}
      printf "           az provider register -n %s\n" "$ns"
    done
  fi
fi

unset _pf05_namespaces _pf05_all _pf05_unregistered _pf05_registering _pf05_ok
