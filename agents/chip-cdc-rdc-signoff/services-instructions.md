# Services execution overlay

This overlay supersedes legacy JSON-in-command instructions. Write exact UTF-8
JSON parameters with WriteResource; mount the returned file URI at
/input/params.json. The registered run function has NO params_json or params_file
argument. Mount additional inputs at their absolute /input paths. Obtain the
actual nodePool ID with GetNodePoolContext. Use outputMounts ["/output"].
Read actual common_design_envelope.json and native evidence. Failed jobs can
lack assets: CDE_JSON= in native logs is the actual persisted envelope.
Never infer engineering pass from framework completion or create envelopes.
Preserve native exit, status and verdict. Missing maps, unresolved flops,
unproven bus coherency and missing synchronizers must remain failures or
not_assessable. Per-bit synchronization is not bus coherency.
Structural analysis does not prove analog metastability, and source-domain
bounded proofs establish only their recorded scope and depth. Do not install
software, scale compute, fabricate maps or repair deliberate negatives.
