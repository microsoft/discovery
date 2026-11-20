# Services execution

Invoke only the registered run function. WriteResource writes literal raw UTF-8
text, not base64. Mount the actual unique JSON FILE URI at /input/params.json
and referenced geometry/technology inputs at their declared paths.
Use the actual GetNodePoolContext ID and outputMounts ["/output"].
The Services action has no params_json field. Nonempty real cell geometry and
correct layer mapping are required for streamout; a merge test is not a
qualified DEF streamout. Read common_design_envelope.json from actual returned
assets, or the persisted CDE_JSON= native log if failed jobs omit assets.
Preserve native failures independently of framework completion.
