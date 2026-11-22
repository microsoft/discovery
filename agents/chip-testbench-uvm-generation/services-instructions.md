# Services execution overlay

This overlay supersedes legacy JSON-in-command instructions. Write exact UTF-8
JSON parameters with WriteResource; mount the returned file URI at
/input/params.json. The registered run function has NO params_json or params_file
argument. Mount additional RTL and testbench files at their /input paths.
Obtain actual nodePool ID with GetNodePoolContext. Use outputMounts ["/output"].
Read common_design_envelope.json and native logs/artifacts. Failed jobs can
lack assets: CDE_JSON= in native logs is the actual persisted envelope.
Never invent envelopes or equate framework completion with engineering pass.
Preserve native exit, status and verdict separately. Generated scaffolds and
DUT linting are not executed self-checking simulation. Absent reference models
require review. tb_non_vacuity must execute positive control and mutants with
actual compiler evidence. Do not install software, scale compute or repair
intentional negative fixtures.

Mutation closure uses the measured testbench_vacuous boolean and the
mutants_unassessable count as explicit gating metrics. A missing assessable
population is null, never a false/zero manufactured to close progress.
