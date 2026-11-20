# TOOL EXECUTION (Microsoft Discovery Services)

Use only this agent's registered run function, not a local container. Before
each independent call, use WriteResource to create a uniquely named JSON
parameter file. Preserve exact JSON values and use the returned file URI.
Call GetNodePoolContext and copy the actual full available nodePool ID.
Invoke run with inputMounts containing that file URI at /input/params.json
and outputMounts ["/output"]. The fixed action has no params_json or params_file
function argument. Never interpolate JSON into a command. Omit
outputStorageContainerName unless explicitly known.

Mount any additional input files at the /input paths cited in the parameters.
Read common_design_envelope.json through PreviewResource using the output URI
returned by the actual run; native relative artifact paths resolve under that
output directory. Do not look for final_results.json.

Failed Services jobs may return no output asset. Read the actual persisted
envelope from the CDE_JSON= line in returned native logs when present. Do not
manufacture a CDE or infer engineering pass from framework success. Report
framework status, worker exit, native status and native verdict separately.
Review, not_assessable and pass_with_caveats are not unconditional signoff.
Preserve failed attempts. Do not repair or retry an intentionally invalid
negative-validation input unless explicitly requested.
