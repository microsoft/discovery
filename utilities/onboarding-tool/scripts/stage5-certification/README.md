# Stage 5 — Certification (`stage5_certify.ps1`)

End-to-end certification with the hero use case (FR5.1). Verifies platform private-endpoint DNS
and 443 reachability, creates a tool, binds it to an agent, opens an investigation + conversation,
sends a prompt, and asserts the tool was actually invoked. Passes only on a real tool invocation,
not just an HTTP 200.

## What it does

- Connectivity check: private-endpoint DNS resolution and TCP 443 to the platform data plane.
- Creates the tool, creates/binds the agent, and creates an investigation + conversation.
- Sends the prompt, polls the response, and asserts a genuine tool invocation.
- Emits a verification summary and persists run state for re-inspection.

## Prerequisites

- PowerShell 7+ (`pwsh`).
- Azure CLI logged in (`az login`) against the target subscription.
- A green Stage 1 `config.json` and a successful Stage 4 deployment (workspace + project +
  chatModel live).
- Network path from where the script runs to the platform private endpoint (run inside the VNet
  or a peered/allowed network).

## Dependencies

- `../lib/OnboardingCommon.psm1` (imported automatically).
- Az CLI with access to the deployed Discovery workspace data plane.

## Parameters

| Parameter | Required | Description |
|---|---|---|
| `-ConfigPath` | yes | Stage 1 `config.json`. |
| `-ResourceGroup` / `-Workspace` / `-Project` | no | Override the config-derived targets. |
| `-ChatModel` | no | Chat model deployment to use (defaults to the deployed one). |
| `-ToolArmId` | no | Reuse an existing tool ARM id instead of creating one. |
| `-Prompt` | no | Override the hero-use-case prompt. |
| `-JsonPath` | no | Write the machine-readable certification report here. |

## Usage

```powershell
./stage5_certify.ps1 -ConfigPath ./config.json -JsonPath ./out/stage5.json
```

## Output & exit codes

- JSON verification summary plus a human pass/fail table; persisted run state.
- Exit `0` = certified (tool really invoked); non-zero = a step failed or no tool invocation.

## Spec

`../../script-specs/stage5-certification/stage5_certify.md`
