# TOOL EXECUTION (Microsoft Discovery Services)

Use only this agent's registered run function. Create a uniquely named JSON
parameter file with WriteResource and mount its actual returned FILE URI at
/input/params.json. Mount immutable sources at their /input paths. There is no
params_json or params_file function argument. Never shell-interpolate JSON.
GetNodePoolContext supplies the exact full nodePool ID. Use outputMounts
["/output"], at most 2 CPU and 4Gi RAM, and a fresh operation for each case.

Default closure requires lint_gate, DEFAULT Verible lint rules, canonical
formatting, no waivers, no selected-rules substitution, no style reclassification
and no disabled formatting gate. lint and format are diagnostic subchecks, not
substitutes for the complete gate. Preserve source hashes and separate proposals.
Read common_design_envelope.json and its native commands/logs from the actual
returned output URI, not final_results.json. Failed jobs can omit assets:
CDE_JSON= in the native log is the exact persisted envelope. Report framework
status, worker exit, native status/verdict and default-rule metrics separately.
A completed/fail CDE is failure even if orchestration reports success.
