# Services execution

Use only the registered run function. Create literal raw UTF-8 JSON with
WriteResource, not base64. Mount its unique actual FILE URI at
/input/params.json plus all referenced layouts and technology inputs.
Call GetResourceContext before running. Resolve attached storage-asset IDs to
the actual listed discovery://resources FILE or DIRECTORY URIs and mount those
URIs; do not pass an unresolved discovery://storageassets alias to the run
function. Preserve the resolved resource-to-asset identity in provenance.
Use the actual GetNodePoolContext ID and outputMounts ["/output"].
The Services action has no params_json field. Real geometric KLayout XOR is
required; identical files alone do not qualify independent Magic/KLayout DEF
streamouts. Missing engines, cell geometry and maps remain blocked.
Read common_design_envelope.json or actual persisted CDE_JSON= in failed native
logs if assets are absent. Never manufacture a passing envelope.
Preserve bound manufacturing-grid precision before LEF import. Default
KLayout/Magic adapter alignment must retain actual DEF terminal geometry on
drawing and explicitly declared port purposes, without changing library masks
or dropping layers. Report the recorded precision and mapping provenance.
Respect the bound Magic technology's minimum engine version. Unsupported
versions and empty or invalid GDS output remain capability failures, never pass.
