# stage5_enable — Stage 5 scenario enablement (consolidated)

Stage 5 · single consolidated PowerShell 7 + Az CLI script · FR mapping: FR5.3–FR5.7
Script: `../../scripts/stage5-scenario-enablement/stage5_enable.ps1`

## Purpose
Prove the platform works end to end: a Discovery Q&A agent (no Discovery tool bound) answers a scientific prompt. A completed run with no assistant text does not certify anything. In-network connectivity probing (formerly FR5.1) moves to Stage 3; tool creation and binding (formerly FR5.2) are out of scope.

## Inputs
- `-ConfigPath <config.json>`; workspace, project, and chat-model deployment names (overridable with `-Workspace`, `-Project`, `-ChatModel`).
- Optional `-Prompt` to replace the default scientific question.

## Behavior
- Probe the workspace data plane, then create agent, create investigation + conversation, send prompt + poll, verify the agent answered.
- Emit the per-service verification summary and a certification verdict.

## Output
- JSON: per-step results plus certification verdict.
- Human: certification report.

## Exit codes
- 0 = certified (all steps green).
- Non-zero = at least one failure (see report).

## Folded steps
Each step ran as a separate sub-script before consolidation; the logic now lives in `stage5_enable.ps1`.

### data_plane_reachable — FR5.3
Read the workspace `publicNetworkAccess` from ARM and `GET ${BASE}/projects/${PROJECT}/agents` from the runner. A non-2xx result fails the check and skips the remaining steps.
- Disabled and unreachable: run Stage 5 from inside the VNet, or set `workspace.publicNetworkAccess=Enabled` and re-run Stage 4.
- Enabled and unreachable: confirm the workspace is Succeeded and the caller has data-plane access.

### create_agent — FR5.3
`POST ${BASE}/projects/${PROJECT}:upsertAgent?api-version=2026-06-01` for `scientistQnAAgent` with `tools = []`, humanInTheLoop=Disabled, and foundryDetails.definition.kind=prompt with model = chat-model deployment name. Poll the operation location until terminal.
- Upsert fails: confirm the workspace data-plane endpoint, chat-model deployment name, and agent schema.

### create_investigation_conversation — FR5.4
`PUT ${BASE}/projects/${PROJECT}/investigations/${INV}`, then `POST ${BASE}/conversations` with `investigationName = /projects/${PROJECT}/investigations/${INV}` (full path) and projectName.
- InvalidRequest on conversation: use the full investigationName path, not the short name.

### send_prompt_poll — FR5.5
`POST ${BASE}/conversations/${CONV}/openai/v1/responses` with message content as an array of parts, an `agent_reference` to the agent, and no `?api-version`, then `GET .../responses/${RID}` until terminal.
- 'api-version not allowed': drop the query param.
- 'requires an element of type Array': send content as an array of parts.

### verify_response — FR5.6
Hard pass/fail: the response must be `completed` and contain non-empty assistant message text. An HTTP 200 alone is not a pass.
- Completed with no text, or not completed: inspect error / last_error / incomplete_details and confirm the chat-model deployment is healthy.

### verification_summary — FR5.7
Confirm supercomputer/workspace/project/chat-model are all Succeeded; Bookshelf (if in scope) has an Approved private endpoint with DNS to the configured BYO storage account (Stage 2 creates it); and agent created, conversation completed, agent answered.
- Any item red: platform is not certified; resolve the named item.