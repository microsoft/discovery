# TOOL EXECUTION (Microsoft Discovery Services)

Use only this agent's registered run function. Create a uniquely named JSON
parameter file with WriteResource and mount its actual returned FILE URI at
/input/params.json. Mount immutable RTL and independently authored testbench files
at their /input paths. No params_json or params_file function argument exists.
Never shell-interpolate JSON. GetNodePoolContext supplies the exact full nodePool
ID. Use outputMounts ["/output"], at most 2 CPU and 4Gi RAM, and fresh operations.

Do not change immutable RTL to satisfy a test. Preserve the independent
self-checking oracle, positive comparisons, zero mismatches, exact TEST PASSED
marker, clean native simulator exit and nonempty VCD. Compile-only lint is not
simulation. Zero-delay GLS is not timing signoff; real cell models and netlist
are required, and SDF coverage is bounded by the actual annotation evidence.
Read common_design_envelope.json and its native compile/run logs and waveform
from the actual output URI, not final_results.json. Failed jobs can omit assets:
CDE_JSON= in the native log is the exact persisted envelope. Report framework
status, worker exit, native status/verdict, versions and counters separately.
completed/fail is failure, never a successful verification result.
