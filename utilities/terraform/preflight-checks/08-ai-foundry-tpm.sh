# shellcheck shell=bash
# -----------------------------------------------------------------------------
# 08-ai-foundry-tpm.sh
#
# Check that the chat model configured in variables.tf (chat_model_name) has
# enough Tokens-Per-Minute (TPM) quota in the target region for Discovery to
# provision its cognition + Bookshelf + Copilot Service deployments.
#
# Numbers ported from the Discovery Toolbox QUOTA_AI_MODELS registry
# (../discovery-toolbox v1.1.67, `src/data/quotaCatalog.ts`):
#
#     gpt-5.2                 default 550K TPM     recommended 4M TPM
#     gpt-5-mini              default 100K TPM     recommended 10M TPM
#     text-embedding-3-large  default  50K TPM     recommended  2M TPM
#
# API: /subscriptions/{sub}/providers/Microsoft.CognitiveServices/locations/
#      {region}/usages?api-version=2023-05-01
#
# Returned `limit` / `currentValue` are in units of 1000 TPM, so multiply
# by 1000 to get real TPM (this is what the toolbox does; see
# `toQuotaResult` in the extension bundle).
#
# Preferred deployment tier ordering (matches toolbox `findBestQuota`):
#   GlobalStandard > DataZoneStandard > Standard > ProvisionedManaged
#
# Failure semantics:
#   - Model has zero quota in the region  -> FAIL (region-model mismatch)
#   - Available < defaultTPM               -> WARN (deploy may hit throttling)
#   - Available < recommendedTPM           -> WARN (below recommended headroom)
#   - Available >= recommendedTPM          -> PASS
# -----------------------------------------------------------------------------

info "8. AI Foundry TPM quota (chat model)"

# Resolve the chat model name from variables.tf / tfvars using the helpers
# already provided by preflight.sh.
_pf08_model=""
_pf08_model="$(read_tfvar     'chat_model_name' 2>/dev/null || true)"
[[ -z "$_pf08_model" ]] && _pf08_model="$(read_tf_default 'chat_model_name' 2>/dev/null || true)"
[[ -z "$_pf08_model" ]] && _pf08_model="gpt-5.2"    # last-resort default (matches variables.tf)

# Registry: model | defaultTPM | recommendedTPM   (TPM in real tokens/min)
_pf08_default_tpm=10000
_pf08_recommended_tpm=50000
case "$_pf08_model" in
  gpt-5.2|gpt-5-2)             _pf08_default_tpm=550000  ; _pf08_recommended_tpm=4000000 ;;
  gpt-5-mini)                  _pf08_default_tpm=100000  ; _pf08_recommended_tpm=10000000 ;;
  text-embedding-3-large)      _pf08_default_tpm=50000   ; _pf08_recommended_tpm=2000000 ;;
  *)                           ;;    # keep generic defaults; will WARN if unknown
esac

_pf08_region_norm=$(echo "$LOCATION" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
_pf08_url="/subscriptions/${SUB_ID}/providers/Microsoft.CognitiveServices/locations/${_pf08_region_norm}/usages?api-version=2023-05-01"
_pf08_json=$(az rest --method get --url "https://management.azure.com${_pf08_url}" 2>/dev/null || true)

if [[ -z "$_pf08_json" || "$_pf08_json" == "null" ]]; then
  warn "  could not query Cognitive Services usages (network / auth / region-not-onboarded issue) -- skipping"
else
  # Search by preferred tier order. Model name is used both raw and with
  # dots/dashes stripped, matching the toolbox's `findBestQuota` fallback.
  _pf08_needle_raw="$_pf08_model"
  _pf08_needle_norm=$(echo "$_pf08_model" | tr -d '.-' | tr '[:upper:]' '[:lower:]')

  _pf08_quota_json=$(echo "$_pf08_json" | jq -c \
    --arg raw "$_pf08_needle_raw" \
    --arg norm "$_pf08_needle_norm" '
      def match_usage(u):
        (u.name.value | ascii_downcase) as $lc
        | ($lc | startswith("openai."))
          and (
            $lc == ("openai.globalstandard."     + ($raw|ascii_downcase)) or
            $lc == ("openai.datazonestandard."   + ($raw|ascii_downcase)) or
            $lc == ("openai.standard."           + ($raw|ascii_downcase)) or
            $lc == ("openai.provisionedmanaged." + ($raw|ascii_downcase)) or
            (($lc | split(".")[2:] | join("") | gsub("[.\\-]"; "")) == $norm)
          );
      # Emit tier + limit + currentValue for the first match, preferring tiers
      # in the canonical order.
      def tier_rank(t): {"globalstandard":0,"datazonestandard":1,"standard":2,"provisionedmanaged":3}[t] // 4;
      [ .value[] | select(match_usage(.))
        | { tier: (.name.value | split(".")[1] | ascii_downcase),
            limit: .limit, current: .currentValue } ]
      | sort_by(tier_rank(.tier))
      | .[0] // empty
    ')

  if [[ -z "$_pf08_quota_json" ]]; then
    fail "  no quota entry for '${_pf08_model}' in ${LOCATION}. Model may not be available in this region -- request access or pick another region."
  else
    _pf08_tier=$(echo    "$_pf08_quota_json" | jq -r '.tier')
    _pf08_limit=$(echo   "$_pf08_quota_json" | jq -r '.limit')
    _pf08_current=$(echo "$_pf08_quota_json" | jq -r '.current')
    # Values are in 1000-TPM units per the ARM API contract.
    _pf08_limit_tpm=$((   _pf08_limit   * 1000 ))
    _pf08_current_tpm=$(( _pf08_current * 1000 ))
    _pf08_avail_tpm=$((   _pf08_limit_tpm - _pf08_current_tpm ))

    # Pretty-print TPM in K/M form.
    _pf08_fmt() {
      local n=$1
      if (( n >= 1000000 )); then printf '%dM' $(( n / 1000000 ))
      elif (( n >= 1000 )); then  printf '%dK' $(( n / 1000 ))
      else printf '%d' "$n"; fi
    }
    _pf08_avail_s=$(_pf08_fmt "$_pf08_avail_tpm")
    _pf08_lim_s=$(_pf08_fmt   "$_pf08_limit_tpm")
    _pf08_def_s=$(_pf08_fmt   "$_pf08_default_tpm")
    _pf08_rec_s=$(_pf08_fmt   "$_pf08_recommended_tpm")

    if (( _pf08_avail_tpm <= 0 )); then
      fail "  ${_pf08_model} in ${LOCATION}: no headroom (limit ${_pf08_lim_s}, tier ${_pf08_tier}). Request a quota increase."
    elif (( _pf08_avail_tpm < _pf08_default_tpm )); then
      warn "  ${_pf08_model} in ${LOCATION}: only ${_pf08_avail_s} available (tier ${_pf08_tier}, limit ${_pf08_lim_s}); below Discovery minimum ${_pf08_def_s}. Deploy may fail; request increase."
    elif (( _pf08_avail_tpm < _pf08_recommended_tpm )); then
      warn "  ${_pf08_model} in ${LOCATION}: ${_pf08_avail_s} available (tier ${_pf08_tier}, limit ${_pf08_lim_s}); meets minimum ${_pf08_def_s} but below recommended ${_pf08_rec_s}."
    else
      pass "  ${_pf08_model} in ${LOCATION}: ${_pf08_avail_s} available (tier ${_pf08_tier}, limit ${_pf08_lim_s}); meets recommended ${_pf08_rec_s}."
    fi
    unset -f _pf08_fmt
  fi
fi

unset _pf08_model _pf08_default_tpm _pf08_recommended_tpm _pf08_region_norm \
      _pf08_url _pf08_json _pf08_needle_raw _pf08_needle_norm _pf08_quota_json \
      _pf08_tier _pf08_limit _pf08_current _pf08_limit_tpm _pf08_current_tpm \
      _pf08_avail_tpm _pf08_avail_s _pf08_lim_s _pf08_def_s _pf08_rec_s
