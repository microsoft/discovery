# Privacy

The Microsoft Discovery Toolbox (this VS Code extension) is built to manage
**your own** Azure resources. It runs entirely inside VS Code on your machine
and talks to Azure on your behalf using credentials you've already signed in
with. This document describes — concretely — what data the extension handles,
where it goes, what it writes to disk, and how to remove it.

> **TL;DR**
>
> - **No automatic telemetry or run-history upload from the public Toolbox.**
>   User-invoked Azure operations, AI features, exports and feedback still
>   transfer the data described below.
> - **No third-party data brokers.** Service calls support the selected Azure
>   scope, directory inspection, catalog/docs access and requested AI work.
> - **Local artifacts.** The extension writes JSONL logs of validation runs,
>   conversations, scorecard runs, and agent deploys under `~/.md-toolbox/`.
>   These can contain resource and identity metadata, prompts, responses and
>   provider errors. Review them before sharing; local storage is not a promise
>   that data selected for an AI call or export never leaves the machine.
> - **Authentication tokens are not deliberately persisted by Toolbox.**
>   VS Code and external sign-in tools manage their own credential stores.

---

## 1. Telemetry and analytics

**The extension collects no telemetry.** There are no calls to
`vscode.telemetry`, Application Insights, `TelemetryReporter`, Google
Analytics, or any other analytics endpoint. There is no opt-out toggle
because there is nothing to opt out of.

VS Code itself collects telemetry independently of this extension — see
[VS Code telemetry settings](https://code.visualstudio.com/docs/getstarted/telemetry).

## 2. Identity and authentication

The extension uses VS Code's built-in authentication providers:

| Provider | Used for | Token lifetime |
|---|---|---|
| `microsoft` | All Azure ARM and Discovery data-plane calls | ~1 hour, auto-refreshed by VS Code |
| `github` | Reading the public [`microsoft/discovery`](https://github.com/microsoft/discovery) catalog repository | Per your VS Code GitHub sign-in |

Toolbox obtains tokens through the selected authentication provider and uses
them in memory. HTTP logging redacts authentication values and known
token values and recognized secret patterns. User-authored prompts, files and
provider error text can still contain sensitive content; review exports before
sharing them rather than treating redaction as a complete privacy filter.

Microsoft Graph reads can resolve account/display labels and directory objects
used by permission and service-principal inspection. Silent diagnostics may
report account/tenant identifiers, granted scopes, HTTP status and request IDs,
but do not return bearer tokens or request new consent to make a check green.
Denied reads stay unverified and do not establish that an identity is missing.
Eligible public-catalog 401/403 responses may be retried anonymously without
forwarding the GitHub credential; private/custom repositories and explicit
backoff do not use that fallback.

## 3. Network endpoints

Common service families and their purpose are listed below. Selected resource
endpoints, configured catalogs and user-invoked links can add feature-specific
destinations; this is not an exhaustive hostname allowlist.

| Host | Purpose | Auth |
|---|---|---|
| `management.azure.com` | Azure Resource Manager — list/read/create/delete resources in **your** subscription | Microsoft session token |
| `graph.microsoft.com` | Directory labels, principal/permission inspection and silent Graph diagnostics | Microsoft session token |
| `*.azurecr.io` | Pull/push container images to **your** Azure Container Registry | ACR credentials sourced from ARM |
| `<workspace>.<region>.api.discovery.microsoft.com` (and similar) | Discovery workspace data plane — investigations, agents, conversations | Microsoft session token |
| `mcp.discovery.azure.com` (when MCP enabled) | Discovery MCP server for tool invocation | Microsoft session token |
| `learn.microsoft.com` | Documentation content and browser links | None |
| `raw.githubusercontent.com/MicrosoftDocs/azure-docs/...` | Fetch Microsoft Discovery documentation pages for the in-extension Docs view | Anonymous HTTP GET |
| `api.github.com` / `raw.githubusercontent.com/microsoft/discovery` | Fetch the Discovery catalog (tool + agent definitions) | Your GitHub session token if you're signed in; anonymous (rate-limited) otherwise |
| `api.github.com/repos/microsoft/discovery/contents/utilities/discovery-toolbox/...` | Fetch the public update manifest and VSIX | GitHub session when available, or anonymous access |

AI-assisted features also use VS Code's selected language-model provider as
described below. The public Toolbox does not automatically upload operational
history to a maintainer dashboard. Other installed extensions have their own
data-handling policies.

## 4. Local files

Artifacts, temporary working files and VS Code-managed state are stored
locally. Configurable export paths may point elsewhere. Removing a local file
does not recall copies already shared or delete Azure resources.

### `~/.md-toolbox/`

Default location: `%USERPROFILE%\.md-toolbox\` (Windows),
`~/.md-toolbox/` (macOS / Linux).

| Subfolder | Contents |
|---|---|
| `deploys/*.jsonl` | Deploy stages, timings, resource IDs, provider details and remediation text. Treat returned service text as potentially sensitive. |
| `conversations/*.jsonl` | One file per conversation thread you've held with a deployed agent. **Includes the full text of every prompt you sent and every response the agent returned.** Includes workspace ARM id, project, investigation, conversation, and agent names. |
| `agent-scorecards/*.jsonl` | One file per scorecard run. **Includes the full prompt sent to each agent, the full response, the LLM judge's rationale, and the judge's confidence bucket.** Includes workspace ARM id, project, and agent names. |
| `validations/*.jsonl` | Stage events/payloads, resource and scope IDs, source-host/build/plan identity, errors and recovery accounting; interaction-related payloads may contain prompts or responses. |
| `manifests/` | Human-reviewable deployment inputs, names, scopes, agent instructions/questions and verification expectations. |
| `reports/` | Exported preflight and diagnostic evidence, including scope and service identifiers. |

Feature-specific caches, run records and explicit output paths can contain
additional local artifacts. Use the displayed artifact path when reviewing or
removing a particular result.

Stop active operations before removing their files. Retain required evidence
and review the selected paths before deletion. Missing directories may be
recreated when the relevant feature runs.

### OS temp directory

The extension stages Bicep parameter files and container build contexts
under your OS temp directory (`%TEMP%` / `/tmp`) for the duration of a
deploy. Files can remain after interruption; do not assume immediate cleanup.

### VS Code workspace storage

Settings, cached selections, UI state and operation history can be retained in
VS Code-managed storage. These may include resource names or scope metadata;
they are not limited to visual preferences.

## 5. AI-assisted features

The **Agent Scorecard** feature uses an LLM to score the responses your
deployed agents return to a sample prompt. The judging call is made
through VS Code's built-in language-model API:
`vscode.lm.selectChatModels({ vendor: 'copilot' })`.

In practice this means: **the prompt you sent to each agent, plus the
response that agent returned, is forwarded to GitHub Copilot using your
own Copilot subscription / license**, so that Copilot can return a score
and rationale. The extension itself does not call any Azure OpenAI
endpoint directly for judging — it delegates to whichever model your
Copilot subscription resolves to.

Validation judging, agent drafting and the chat surface can also send selected
prompts, responses, tool results or configuration context through VS Code's
language-model API. Use these features only with data permitted for that
provider. Their transport and retention policies are separate from Toolbox's
local artifact storage.

Discovery conversations and MCP calls send the selected prompts/inputs to the
workspace or service endpoint involved in that operation. Do not invoke AI
features with content you are not permitted to send to those services.

## 6. Activity log

The "Activity Log" view shows the most recent ~500 HTTP requests and
actions the extension has performed in the current session. It is
in-memory by default and is cleared when you reload the window. Related
operation errors and correlation details can also be retained in persisted
run/deploy artifacts or user-requested exports and chat-tool responses. Review
that content before sharing it.

## 7. Sensitive operational data

Toolbox does not add background behavioral tracking or keystroke collection.
Operational data can nevertheless include account labels, directory IDs,
tenant/subscription IDs, source-host names, resource names and user-selected
file or prompt content. Network services receive ordinary request metadata.
Keep credentials out of prompts and manifests, review diagnostic output, and
apply your organization's retention and sharing rules to local artifacts.

## 8. How to remove all extension data

1. Finish or safely stop active operations and retain any evidence you need.
2. Review and remove the desired artifacts under `~/.md-toolbox/` and any
  explicitly selected output paths. This does not recall exported copies.
3. Use Toolbox's **Reset to First-Run** for its settings/state, reviewing the
  confirmation. VS Code account credentials are managed separately by VS Code
  and any external authentication tools.
4. Azure resource deletion is a separate, explicitly approved operation. Use
  scoped inventory/cleanup previews; removing local files or uninstalling the
  extension does not delete deployed resources.

## 9. Reporting privacy concerns

If you spot a behavior of this extension that contradicts anything in
this document, please open an issue on the public release repository
at [`microsoft/discovery`](https://github.com/microsoft/discovery/issues/new?labels=feedback&title=%5BPrivacy%5D%20)
or contact the maintainers.

The "Send Feedback" entry in the Discovery Toolbox sidebar is hidden
by default to keep the surface minimal. Set `mdToolbox.showFeedback`
to `true` in VS Code Settings if you want a one-click pre-filled
issue form that includes your current toolbox version, active page,
tenant id, subscription id, region, and resource group. Review the
pre-filled body before submitting — the GitHub issue is public.

---

<sub>Privacy notice for Discovery Toolbox **v1.11.66** · built from `ed3b0a3` on 2026-11-13T18:45:33.204Z.</sub>

<sub>This public Toolbox notice is distributed in the [`microsoft/discovery`](https://github.com/microsoft/discovery/tree/main/utilities/discovery-toolbox) release folder. Other installed extensions have their own policies; for VS Code's privacy practices see the [VS Code privacy statement](https://code.visualstudio.com/license).</sub>
