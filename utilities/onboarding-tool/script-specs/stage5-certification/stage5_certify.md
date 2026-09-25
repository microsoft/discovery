# stage5_certify — Stage 5 certification (consolidated)

Stage 5 · single consolidated PowerShell 7 + Az CLI script · FR mapping: FR5.1–FR5.7
Script: `../../scripts/stage5-certification/stage5_certify.ps1`

## Purpose
Prove the platform works: connectivity, then a real agent run that genuinely invokes a tool on the supercomputer. A completed run alone does not certify anything.

## Inputs
- `--config <config.json>`; workspace, project, and chat-model deployment names.

## Behavior
- Run connectivity, then create tool, create agent + bind tool, create investigation + conversation, send prompt + poll, assert tool invocation.
- Emit the per-service verification summary and a certification verdict.

## Output
- JSON: per-step results plus certification verdict.
- Human: certification report.

## Exit codes
- 0 = certified (all steps green).
- Non-zero = at least one failure (see report).

## Folded steps
Each step ran as a separate sub-script before consolidation; the logic now lives in `stage5_certify.ps1`.

### connectivity_check — FR5.1
Resolve each platform privatelink FQDN to a private IP from inside the VNet and confirm reachability (reuse the Stage 3 harness).
- Unreachable/public IP: fix private DNS links / PE approval before certifying.

### create_tool — FR5.2
`PUT https://management.azure.com${TOOL_ARM_ID}?api-version=2026-06-01`; verify `provisioningState=Succeeded` and `definitionContent` present. Tool JSON must carry version, definitionContent (name/description/version/category/infra[]), and code_environments[].infra_node matching an infra[].name.
- infra_node mismatch: align code_environments[].infra_node with an infra[].name.

### create_agent_bind_tool — FR5.3
`PUT ${BASE}/projects/${PROJECT}:upsertAgent` with top-level `tools[]` carrying the tool ARM id, humanInTheLoop=Disabled, confirmation=Disabled, and foundryDetails.definition.kind=prompt with model = chat-model deployment name. Agent instructions must call GetNodePoolContext first, or the model may answer from memory and never touch the supercomputer.
- No tool call at run time: confirm instructions call GetNodePoolContext first.

### create_investigation_conversation — FR5.4
`PUT ${BASE}/projects/${PROJECT}/investigations/${INV}`, then `POST ${BASE}/conversations` with `investigationName = /projects/${PROJECT}/investigations/${INV}` (full path) and projectName.
- InvalidRequest on conversation: use the full investigationName path, not the short name.

### send_prompt_poll — FR5.5
`POST ${BASE}/conversations/${CONV}/openai/responses` with message content as an array of parts and no `?api-version` on the /v1/ path, then `GET .../responses/${RID}` until terminal.
- 'api-version not allowed' on /v1/: drop the query param.
- 'requires an element of type Array': send content as an array of parts.

### assert_tool_invocation — FR5.6
Hard pass/fail: require the response output to contain a function_call / function_call_output item and confirm the run is visible in Foundry tracing. Absence of a tool-call item is a FAIL.
- Completed but no tool call: agent answered from memory; fix instructions (GetNodePoolContext first) and re-run.

### verification_summary — FR5.7
Confirm supercomputer/workspace/Foundry/project/chat-model all Succeeded; Bookshelf (if in scope) has 3 PEs approved with DNS; and tool created, agent created, tool bound, conversation completed, tool actually invoked.
- Any item red: platform is not certified; resolve the named item.
