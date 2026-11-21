# Services execution qualification

The registered `run` action has no `params_json` argument. Write UTF-8 scenario
JSON with WriteResource and mount its returned FILE URI at `/input/params.json`.
Request `/output` as the output mount. Mount each referenced design file
using its actual returned WriteResource FILE URI, never an inferred physical
storage path. Preserve the PDK binding and use the actual GetNodePoolContext ID.
An OpenDB operation must execute the real native engine.

Read `/output/common_design_envelope.json`, native logs, and produced database
artifacts. Framework completion is not an engineering pass. Domain fail,
not_assessable, and missing verdicts exit nonzero. Native `CDE_JSON=` reproduces
the exact persisted envelope even when failed jobs omit output assets.
Review/caveats are not clean signoff. Qualify only scenarios actually tested.
