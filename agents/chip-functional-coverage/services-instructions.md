# Services execution overlay

This overlay supersedes legacy JSON-in-command instructions. Write exact UTF-8
JSON parameters with WriteResource; mount the returned file URI at
/input/params.json. The registered run function has NO params_json or params_file
argument. Mount RTL and cocotb files at the /input paths named in parameters.
Obtain actual nodePool ID with GetNodePoolContext. Use outputMounts ["/output"].
Read common_design_envelope.json, actual simulation samples, native coverage
database, logs and reachability proof. Failed jobs can lack assets: CDE_JSON=
in native logs is the actual persisted envelope. Never manufacture envelopes.
Only measure_rtl_coverage executes the DUT; caller-supplied sample scoring is
not simulation evidence. Zero samples, no testcases, missing native data or
engines block closure. Preserve native exit, status and verdict separately.
Do not install software, scale compute, invent sampled bins or alter deliberate
negative stimulus. Framework completion is not engineering pass.
