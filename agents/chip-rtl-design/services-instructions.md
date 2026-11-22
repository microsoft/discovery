# TOOL EXECUTION (Microsoft Discovery Services)

Use only this agent's registered run function. Create a uniquely named JSON
parameter file with WriteResource and mount its actual returned FILE URI at
/input/params.json. Mount immutable RTL files at the /input paths in that JSON.
The action takes no params_json or params_file argument; never shell-interpolate
JSON or rewrite supplied RTL. GetNodePoolContext supplies the exact full nodePool
ID. Use outputMounts ["/output"], at most 2 CPU and 4Gi RAM, and fresh operations.

Read common_design_envelope.json from the actual returned output URI, not
final_results.json. Read its referenced native commands, Yosys log, netlist and
formatting proposals as needed. Failed jobs can omit output assets: CDE_JSON=
in the native worker log is an exact copy of the persisted envelope, not a
replacement result. Report framework status, worker exit, native status and
verdict separately. completed/fail, review and not_assessable are not pass.
check_authored verifies authored RTL; it does not generate RTL or prove function.
File-input formatting proposals never authorize changing the immutable source.
