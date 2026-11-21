# Services execution contract (qualification39)

For `sweep`, `pareto_search` and `sensitivity`, this worker filters the supplied
source-CDE-backed measured points; it does not read a Liberty file or launch a
PDK flow. PDK/corner/library hashes on points are provenance metadata, not
instructions to mount a library file. Mount the requested parameter file and
the authentic retained source CDE files required for validation. NEVER create
placeholder libraries, models, solvers, engines,
PDKs or other dependency substitutes. If an actual required dependency cannot
be resolved, report blocked/not_assessable instead of fabricating one.
This section overrides the legacy HOW TO CALL instructions. The registered run action is a source-backed fixed-file action with NO params_json or params_file arguments. Write the exact JSON parameter object to a uniquely named file using WriteResource. Mount the actual returned FILE URI at /input/params.json, preserving any other input files at their documented absolute /input paths. Use outputMounts ["/output"]. Use GetNodePoolContext and the actual full nodePool ID. Jobs are limited to 2 CPU/4Gi. The immutable fix1 engine image is digest-pinned; services-overlay.py applies only hash-checked source-backed bug fixes before the native worker runs. No solver or engine is replaced. TMPDIR=/workdir keeps reducer scratch under the work directory. A completed CDE with validation.fail or not_assessable exits 1. Failed-job output may be unavailable; retain the exact native CDE_JSON= line from its logs. Never turn framework success, status completed, estimates, or missing evidence into engineering pass. Report actual invocation ID, domain verdict, native status/exit, engine version, metrics and actual CDE/artifact URIs. Do not retry deliberate negative fixtures.
Source validation follow-up: every point requires an ACTUAL mounted source CDE
file and exact file-byte source_cde_sha256. A reference string alone is not
validated evidence. The worker checks source status/verdict, closed progress,
blocking alignment and equality of every claimed finite measured metric.
Open/missing upstream acceptance blocks recommendations; mismatched hashes or
metrics fail. Never manufacture a passing/closed source CDE, an objective value,
or an over-budget fallback recommendation. Supply authentic retained native CDE
files as immutable input assets, not model-authored substitutes.
