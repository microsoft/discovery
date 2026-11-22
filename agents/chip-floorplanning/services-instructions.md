# Services execution qualification

The registered `run` action accepts no `params_json` or `params_file` argument.
Write the scenario JSON as UTF-8 with WriteResource and mount its actual returned
FILE URI read-only at `/input/params.json`; request `/output` as an output mount.
Create referenced design files with WriteResource and mount their actual returned FILE URIs individually;
do not infer resource URIs from physical storage paths. Preserve the supplied PDK
binding and timing intent. Use the actual GetNodePoolContext ID.

The authoritative output is `/output/common_design_envelope.json`. Inspect its
status and validation verdict, plus the native engine log and stage artifact.
Framework completion alone is not an engineering pass. Domain fail,
not_assessable, or an absent verdict exits nonzero. `CDE_JSON=` in native logs is
the exact persisted envelope, including failed jobs whose assets are omitted.
Review and pass_with_caveats are not clean signoff. Execute only the requested
scenario; smoke qualification does not establish support for all scenarios.
