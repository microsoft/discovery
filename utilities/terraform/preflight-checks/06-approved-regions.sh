# shellcheck shell=bash
# -----------------------------------------------------------------------------
# 06-approved-regions.sh
#
# Positive allowlist: the target region must appear in the Discovery-approved
# region list. Complements the KNOWN_BAD_REGIONS blocklist in check 2 --
# blocklist catches regions the RP falsely advertises support for, allowlist
# catches regions that were never in scope to begin with.
#
# Default allowlist mirrors `DEFAULT_APPROVED_REGIONS` in the Discovery
# Toolbox (`../discovery-toolbox` v1.1.67):
#     "East US, Sweden Central, UK South"  =>  eastus, swedencentral, uksouth
# Update by editing the array below, or override at runtime via env var:
#     PREFLIGHT_APPROVED_REGIONS="eastus,uksouth" ./preflight.sh
# -----------------------------------------------------------------------------

info "6. Approved regions (Discovery allowlist)"

_pf06_default_allowlist=(eastus swedencentral uksouth)

if [[ -n "${PREFLIGHT_APPROVED_REGIONS:-}" ]]; then
  # Split comma-separated env var into an array, normalising each entry.
  IFS=',' read -r -a _pf06_allowlist <<< "$PREFLIGHT_APPROVED_REGIONS"
  _pf06_source="env override (PREFLIGHT_APPROVED_REGIONS)"
else
  _pf06_allowlist=("${_pf06_default_allowlist[@]}")
  _pf06_source="built-in default (mirrors Discovery Toolbox)"
fi

_pf06_loc=$(echo "$LOCATION" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
_pf06_matched=false
_pf06_normalised=()
for r in "${_pf06_allowlist[@]}"; do
  n=$(echo "$r" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
  _pf06_normalised+=("$n")
  [[ "$n" == "$_pf06_loc" ]] && _pf06_matched=true
done

if $_pf06_matched; then
  pass "  ${LOCATION} is in the approved list [${_pf06_normalised[*]}] (source: ${_pf06_source})"
else
  fail "  ${LOCATION} is NOT in the approved list [${_pf06_normalised[*]}] (source: ${_pf06_source}). Pick an approved region, or if this is intentional, override with PREFLIGHT_APPROVED_REGIONS=..."
fi

unset _pf06_default_allowlist _pf06_allowlist _pf06_source _pf06_loc _pf06_matched _pf06_normalised
