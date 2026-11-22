# Services execution overlay

This overlay supersedes legacy JSON-in-command instructions. Write exact UTF-8
JSON parameters with WriteResource; mount the returned file URI at
/input/params.json. The registered run function has NO params_json or params_file
argument. Mount additional inputs at their absolute /input paths. Obtain the
actual nodePool ID with GetNodePoolContext. Use outputMounts ["/output"].
Read common_design_envelope.json and real coverage.dat counters, simulation
logs and reachability proof. Failed jobs can lack assets: CDE_JSON= in native
logs is the actual persisted envelope, never manufacture a replacement.
Framework completion is not engineering pass. Preserve native exit, status
and verdict. An instrumentation-only build has no measured hit rates.
Unsupported metrics and missing engines remain not_assessable; do not invent
counters, waive reachable holes, install software, scale compute or repair
deliberately incomplete stimulus.
