# Services execution

Use the registered run function with a caller-created literal raw UTF-8 JSON
WriteResource file mounted at /input/params.json. WriteResource does not decode
base64. Mount all referenced routed DEF, technology/cell LEF, library and
hash-pinned corner RC-rule files. The Services action has no params_json field.
Use GetNodePoolContext's actual ID and outputMounts ["/output"]. Do not install
dependencies, fabricate RC data or replace missing decks with defaults.
Read common_design_envelope.json; failed jobs may omit assets, in which case
native CDE_JSON= records the actual persisted envelope. Report framework status,
worker exit, native verdict and extracted/required corners separately.
