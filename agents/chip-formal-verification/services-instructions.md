# Services execution overlay

This overlay supersedes legacy JSON-in-command instructions. Write exact UTF-8
JSON parameters with WriteResource; mount the returned file URI at
/input/params.json. The registered run function has NO params_json or params_file
argument. Mount additional inputs at their absolute /input paths. Obtain the
actual nodePool ID with GetNodePoolContext. Use outputMounts ["/output"].
Read actual common_design_envelope.json and solver logs/witnesses from the
returned output asset. Failed jobs can lack assets: CDE_JSON= in the native log
is the actual persisted envelope. Never author substitute envelopes.
Framework completion does not mean engineering pass. Preserve native exit,
status and verdict. Missing engines, unknown or unreached covers block closure.
Bounded proof establishes only the recorded depth; a reached antecedent cover
provides nonvacuity evidence, while a counterexample is a genuine failure.
Do not install software, scale compute, alter assertions, or repair negative
fixtures. OSS Yosys requires immediate assertions, not clocked concurrent SVA.
