# Services execution qualification

The registered `run` action accepts no `params_json` or `params_file` argument.
Write the scenario JSON as UTF-8 with WriteResource and mount its actual returned
FILE URI read-only at `/input/params.json`; request `/output` as an output mount.
Mount referenced design FILE URIs individually. Preserve supplied SDC, SPEF, baseline reports, PDK views,
and timing intent. Use the actual GetNodePoolContext ID. An ECO wave must be
scoped, checkpointed, reversible, and execute a genuine mutation rather than a
successful no-op. Do not equate analysis-only smoke with a qualified ECO wave.

Read `/output/common_design_envelope.json`, native logs, and committed or
rejected/rollback artifacts. Framework completion is not an engineering pass.
Domain fail, not_assessable, and missing verdicts exit nonzero. `CDE_JSON=` logs
the exact persisted envelope when failed jobs omit assets. Review/caveats are
not clean signoff. Qualify only scenarios actually executed.
