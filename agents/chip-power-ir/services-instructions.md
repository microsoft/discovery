# Services execution

Use only the registered run function. WriteResource content is literal raw
UTF-8 JSON, not base64; mount its actual file URI at /input/params.json, all
referenced inputs at their declared paths, and outputMounts ["/output"].
Use GetNodePoolContext's actual ID. The Services action has no params_json field.
Require a real power network, PDK libraries and declared activity; do not turn
missing network/activity/IR limits into fabricated measurements or defaults.
Read common_design_envelope.json from actual returned assets, or the actual
persisted CDE_JSON= in failed native logs when assets are absent. Report worker
exit, framework status and native status/verdict independently.
Only explicit passing-family native verdicts permit worker exit 0. A completed
envelope with review, missing verdict, or disconnected-PDN not_assessable checks
must remain a nonzero worker result; preserve its actual CDE and PSM errors.
