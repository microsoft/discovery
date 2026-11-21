# Services execution qualification

The registered `run` action has no `params_json` argument. Write UTF-8 scenario
JSON with WriteResource and mount its returned FILE URI at `/input/params.json`.
Request `/output` as the output mount. Mount referenced design files at their
specified paths using actual WriteResource FILE URIs. Require a valid placed
input, real PDK views, and supplied clock intent. Never invent clock periods or
budgets. Use the actual GetNodePoolContext ID.

Read `/output/common_design_envelope.json`, native logs, and post-CTS artifacts.
Framework completion is not an engineering pass. Domain fail, not_assessable,
and missing verdicts exit nonzero. Native `CDE_JSON=` is the exact persisted
envelope when failed jobs omit assets. Review/caveats are not clean signoff.
Qualification applies only to scenarios actually executed.
