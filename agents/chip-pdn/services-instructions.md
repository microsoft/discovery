# Services execution qualification

The registered `run` action has no `params_json` argument. Write UTF-8 scenario
JSON with WriteResource and mount its returned FILE URI at `/input/params.json`.
Request `/output` as the output mount. Mount each referenced design file using
its actual WriteResource FILE URI, not an inferred directory URI. Preserve the
PDK binding and use the actual GetNodePoolContext ID. Never synthesize a physical
pass from missing connectivity evidence.

Read `/output/common_design_envelope.json`, native logs, and the PDN artifact.
Framework completion is not an engineering pass. Domain fail, not_assessable,
and missing verdicts exit nonzero. The native `CDE_JSON=` log contains the exact
persisted envelope when failed Services jobs omit assets. Review/caveats are not
clean signoff. Qualification is restricted to the scenarios actually tested.
