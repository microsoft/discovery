# Services execution overlay

This overlay supersedes legacy JSON-in-command instructions. Write exact UTF-8
JSON parameters with WriteResource; mount the returned file URI at
/input/params.json. The registered run function has NO params_json or params_file
argument. Mount additional inputs at their absolute /input paths. Obtain the
actual nodePool ID with GetNodePoolContext. Use outputMounts ["/output"].
Do not install software, scale compute, alter intent, or retry a domain-negative
case to turn it into a pass. Read actual common_design_envelope.json and native
artifacts from the returned output asset; legacy final_results.json is obsolete.
Failed jobs can lack assets: CDE_JSON= in the native log is the actual persisted
envelope, not an invitation to manufacture one. Framework completion does not
mean engineering pass; preserve native exit, status and verdict separately.
Review/caveats are not unconditional signoff. Structural SVA authoring and
vacuity screening are not solver proofs or full SVA checkability.
