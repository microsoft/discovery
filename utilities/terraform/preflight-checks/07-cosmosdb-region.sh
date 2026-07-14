# shellcheck shell=bash
# -----------------------------------------------------------------------------
# 07-cosmosdb-region.sh
#
# Verify Microsoft.DocumentDB (Cosmos DB) is available in the target region.
# Discovery workspaces auto-provision a managed Cosmos account at
# workspace-creation time; if the region isn't Cosmos-supported the async LRO
# fails after the workspace PUT is accepted, which surfaces late as a
# confusing terraform error.
#
# Per MS Learn there is no per-subscription RU/s quota (throughput is managed
# per Cosmos account), so this is purely a region-availability check --
# matching the shape of the Discovery Toolbox `quota.cosmosdb.throughput`
# check (which is also mostly informational: it queries the same
# `Microsoft.DocumentDB/locations` endpoint used here).
#
# API: /subscriptions/{sub}/providers/Microsoft.DocumentDB/locations
#      (api-version=2024-05-15)
# -----------------------------------------------------------------------------

info "7. Cosmos DB region support"

_pf07_url="/subscriptions/${SUB_ID}/providers/Microsoft.DocumentDB/locations?api-version=2024-05-15"
_pf07_json=$(az rest --method get --url "https://management.azure.com${_pf07_url}" 2>/dev/null || true)

if [[ -z "$_pf07_json" || "$_pf07_json" == "null" ]]; then
  warn "  could not query Cosmos DB locations (network / auth issue) -- skipping"
else
  _pf07_loc=$(echo "$LOCATION" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
  _pf07_supported=$(echo "$_pf07_json" \
    | jq -r --arg loc "$_pf07_loc" '
        .value // []
        | map((.name // "") | ascii_downcase | gsub(" "; ""))
        | any(. == $loc)')

  if [[ "$_pf07_supported" == "true" ]]; then
    pass "  Microsoft.DocumentDB is available in ${LOCATION}"
  else
    fail "  Microsoft.DocumentDB is NOT available in ${LOCATION}. Discovery workspace creation will fail its Cosmos provisioning LRO. Pick a different region."
  fi
fi

unset _pf07_url _pf07_json _pf07_loc _pf07_supported
