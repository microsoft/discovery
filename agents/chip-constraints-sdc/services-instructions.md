# Services execution

Use the registered run function only. WriteResource takes literal raw UTF-8
JSON, not base64. Create a unique parameter resource and mount its actual FILE
URI at /input/params.json with outputMounts ["/output"]. Mount all referenced
libraries, netlists and SDC files. Copy the actual GetNodePoolContext ID.
The Services action has no params_json argument. Never interpolate JSON into
shell commands. Read common_design_envelope.json; if a failed job omits assets,
read the actual persisted CDE_JSON= line in native logs. Report framework status,
worker exit, native status/verdict and measured endpoint population separately.
Never invent timing intent, endpoint counts or a passing envelope. Missing
periods and I/O budgets remain named holes. Preserve negative fixtures.
