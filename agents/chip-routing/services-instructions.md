# Services execution qualification

Keep the existing single-line `params_json` contract. Mount each supplied file
using its actual returned WriteResource FILE URI. Require a valid post-CTS input
and real PDK views. Preserve timing intent and use the actual GetNodePoolContext
ID; do not manufacture a physical pass from missing connectivity or DRC data.

Read `/output/common_design_envelope.json`, the native engine log, and routed
artifacts. Framework completion is not an engineering pass. Domain fail,
not_assessable, and missing verdicts exit nonzero. Native `CDE_JSON=` contains the
exact persisted envelope, including failed jobs without returned assets.
Review/caveats are not clean signoff. Qualify only scenarios actually tested.
