# Services execution

Use the registered run function only. Create a uniquely named JSON file with
WriteResource using literal raw UTF-8 content, not base64 or compressed text.
Mount its returned file URI at /input/params.json and every referenced input at
its declared path. Use the actual GetNodePoolContext ID and outputMounts
["/output"]. The Services action has no params_json argument: do not interpolate
JSON into a shell command. Read common_design_envelope.json from the returned
output asset. Failed jobs can omit assets; CDE_JSON= in native logs is the actual
persisted envelope, not a generated summary. Keep framework status, worker exit,
native status and verdict separate. Review, missing evidence and pre-layout
estimates are not signoff. Never repair intentional negative fixtures.
