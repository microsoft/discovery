# Services execution qualification

Keep the existing single-line `params_json` contract. Create the supplied input
files with WriteResource and mount their actual returned FILE URIs individually.
Preserve the PDK binding, supplied SDC, and timing intent; do not invent budgets.
Use the actual GetNodePoolContext ID.

Read `/output/common_design_envelope.json`, the native engine log, and placed
artifacts. Framework completion is not an engineering pass. Domain fail,
not_assessable, and missing verdicts exit nonzero. Native `CDE_JSON=` reproduces
the exact persisted envelope, including failures without returned assets.
Review/caveats are not clean signoff. Only tested scenarios are qualified.
