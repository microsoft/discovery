# Public message catalog. Every warning/error that reaches public output (console,
# step summary, annotations, artifacts, Pages) is rendered from these templates.
# Parameters are sanitized to a strict character allowlist before substitution.
# Raw details (logs, API bodies) go only to private evidence.
@{
  # Preflight / environment
  'DH-PRE-001' = 'Azure CLI is not authenticated or the subscription is not accessible.'
  'DH-PRE-002' = 'Resource {resource} is not tagged {tag}=true; refusing to use it for tests.'
  'DH-PRE-003' = 'Required configuration is missing or invalid: {fields}.'
  'DH-PRE-004' = 'Required command is unavailable: {command}.'
  'DH-PRE-005' = 'Discovery workspace or project is not reachable (HTTP {status}).'
  'DH-PRE-006' = 'Nodepool {nodepool} is not reachable (HTTP {status}).'
  'DH-PRE-007' = 'Preflight failed; dependent Azure stages were not attempted.'
  'DH-PRE-008' = 'Evidence storage is not reachable (HTTP {status}); private evidence is kept on the runner only.'

  # Discovery of catalog content
  'DH-DSC-001' = 'Agent folder is missing required file {file}.'
  'DH-DSC-002' = 'YAML could not be parsed: {file}.'
  'DH-DSC-003' = 'Build context contains an unsupported symlink or submodule: {path}.'
  'DH-DSC-004' = 'Git LFS content is missing for {path}; fetch LFS objects before testing.'
  'DH-DSC-005' = 'Build context exceeds limit ({size} MB > {limit} MB).'
  'DH-DSC-006' = 'tool.yaml has no usable image reference (infra[].image.acr).'
  'DH-DSC-007' = 'tool.yaml has no usable name.'
  'DH-DSC-008' = 'Tool folder has no Dockerfile.'
  'DH-DSC-009' = 'Normalized {count} file(s) from CRLF to LF to match .gitattributes (local checkout only).'
  'DH-DSC-010' = 'Agent tool binding {placeholder} could not be mapped to a tool folder.'
  'DH-DSC-011' = 'Tool {tool} is not bound by the agent (no matching toolId in discoveryExtensions.tools).'
  'DH-DSC-012' = 'Unknown agent requested: {agent}.'
  'DH-DSC-013' = 'Tool defines multiple distinct images; only single-image tools are supported.'
  'DH-DSC-014' = 'Uncommitted or untracked files were included (worktree source).'
  'DH-DSC-015' = 'Agent is not a prompt agent (kind={kind}).'

  # Specs
  'DH-SPC-001' = 'Spec is invalid: {reason}.'
  'DH-SPC-002' = 'Expired skip ignored for stage {stage} (until {until}).'
  'DH-SPC-003' = 'Stage skipped by spec until {until}.'
  'DH-SPC-004' = 'Spec changes in this PR are inactive until merged; main spec used.'

  # Build / image smoke
  'DH-BLD-001' = 'Image build failed.'
  'DH-BLD-002' = 'Image build failed: build agent ran out of disk space.'
  'DH-BLD-003' = 'Image build timed out after {minutes} minutes.'
  'DH-BLD-004' = 'Image build could not be queued.'
  'DH-BLD-005' = 'Image push failed.'
  'DH-BLD-006' = 'Base image could not be pulled.'
  'DH-BLD-007' = 'A network download inside the Dockerfile failed.'
  'DH-BLD-008' = 'Reused image {tag} for unchanged tool fingerprint (built {age} days ago).'
  'DH-BLD-009' = 'Image built: {tag}.'
  'DH-BLD-010' = 'Build run ended with status {status}.'
  'DH-SMK-001' = 'Image smoke check {name} failed (exit {exit}).'
  'DH-SMK-002' = 'Image smoke check {name} produced no result marker (no shell in image or step crashed).'
  'DH-SMK-003' = 'Image smoke check {name} output did not contain expected text #{index}.'
  'DH-SMK-004' = 'Image smoke results reused from ledger for {tag}.'
  'DH-SMK-005' = 'All {count} image smoke check(s) passed.'
  'DH-SMK-006' = 'Image smoke log could not be retrieved from ACR; smoke results are inconclusive.'

  # Tool registration
  'DH-REG-001' = 'Tool registration request was rejected (HTTP {status}).'
  'DH-REG-002' = 'Tool provisioning ended in state {state}.'
  'DH-REG-003' = 'Tool provisioning timed out after {minutes} minutes.'
  'DH-REG-004' = 'Tool registration unchanged (definition hash matches); reused.'
  'DH-REG-005' = 'No image exists for this tool fingerprint; run the build stage first.'
  'DH-REG-006' = 'Tool registered and provisioned.'

  # Tool run
  'DH-RUN-001' = 'Tool run {case} ended with status {status}.'
  'DH-RUN-002' = 'Tool run {case}: expected output #{index} not found in logs.'
  'DH-RUN-003' = 'Tool run {case}: validation receipt check failed ({reason}).'
  'DH-RUN-004' = 'Tool run {case} waited {minutes} minutes in queue without starting (capacity).'
  'DH-RUN-005' = 'Tool run {case} exceeded {minutes} minutes while running.'
  'DH-RUN-006' = 'No configured nodepool matches the tool SKUs; tool execution not tested.'
  'DH-RUN-007' = 'No deterministic tool-run spec for this action tool; tool execution not tested.'
  'DH-RUN-008' = 'Tool run request was rejected (HTTP {status}).'
  'DH-RUN-009' = 'No registered tool resource found for this fingerprint; run tool-register first.'
  'DH-RUN-010' = 'All {count} tool run case(s) passed.'
  'DH-RUN-011' = 'Tool run {case}: action {action} is not defined in tool.yaml.'

  # Agent registration
  'DH-AGT-001' = 'Agent upsert was rejected (HTTP {status}).'
  'DH-AGT-002' = 'Agent deployment operation ended with status {status}.'
  'DH-AGT-003' = 'Agent registered as {name}.'
  'DH-AGT-004' = 'Agent references top-level tools of kind {kinds} which this contract does not deploy; those bindings are not tested.'
  'DH-AGT-005' = 'Agent requires trusted template variables ({variables}) that are not available in this run.'
  'DH-AGT-006' = 'Agent deployment operation did not finish within {minutes} minutes.'

  # Round trip
  'DH-RTP-001' = 'Round trip failed: {reason}.'
  'DH-RTP-002' = 'Round trip did not call bound tool {tool}.'
  'DH-RTP-003' = 'Agent requested user confirmation; unattended tests cannot approve.'
  'DH-RTP-004' = 'Round trip timed out after {minutes} minutes.'
  'DH-RTP-005' = 'Round trip passed with verified tool execution ({tools}).'
  'DH-RTP-006' = 'Round trip passed (tool-less agent smoke).'
  'DH-RTP-007' = 'No deterministic round-trip spec exercises the tools of this agent; tool round trip not tested.'
  'DH-RTP-008' = 'Round trip exercised {called} of {total} bound tool(s).'
  'DH-RTP-009' = 'Expected response text #{index} not found.'
  'DH-RTP-010' = 'Round-trip request was rejected (HTTP {status}).'
  'DH-RTP-011' = 'Round trip disabled by configuration.'

  # Dependencies / scheduling
  'DH-DEP-001' = 'Not attempted: dependency {dependency} ended {status}.'
  'DH-DEP-002' = 'Not attempted: run budget for {class} exhausted.'
  'DH-DEP-003' = 'Not attempted before the run deadline.'
  'DH-DEP-004' = 'Cancelled at the run deadline or on cancellation; remote operation was cancelled.'
  'DH-DEP-005' = 'Not attempted: preflight failed.'

  # Infrastructure / generic
  'DH-INF-001' = 'Transient service error (HTTP {status}) persisted after retries.'
  'DH-INF-002' = 'Authorization failed (HTTP {status}); check role assignments.'
  'DH-INF-003' = 'Network error contacting {service}.'
  'DH-GEN-001' = 'Unexpected harness error in stage {stage}.'
  'DH-RPT-001' = 'No result recorded (shard lost, cancelled, or interrupted).'
  'DH-CLN-001' = 'Cleanup: {action} {target}.'
  'DH-CLN-002' = 'Cleanup step {step} failed (HTTP {status}).'
}
