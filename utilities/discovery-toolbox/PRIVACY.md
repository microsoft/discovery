# Privacy

The Microsoft Discovery Toolbox (this VS Code extension) is built to manage
**your own** Azure resources. It runs entirely inside VS Code on your machine
and talks to Azure on your behalf using credentials you've already signed in
with. This document describes — concretely — what data the extension handles,
where it goes, what it writes to disk, and how to remove it.

> **TL;DR**
>
> - **No telemetry.** The extension does not send any usage data, error
>   reports, or analytics anywhere.
> - **No third-party data brokers.** All network calls go to Azure (your
>   subscription), Microsoft Graph (your identity), GitHub (the public
>   Discovery catalog + docs), or your own deployed Discovery workspace.
> - **Local artifacts.** The extension writes JSONL logs of validation runs,
>   conversations, scorecard runs, and agent deploys under `~/.md-toolbox/`.
>   These contain workspace metadata and, for conversations + scorecards,
>   the full text of prompts and responses you exchanged with agents. They
>   never leave your machine and you can delete them at any time.
> - **No persistent credentials.** Azure and GitHub access tokens are
>   acquired through VS Code's built-in authentication providers, held in
>   memory, and discarded; they are never written to any file the extension
>   controls.

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
| `github` | Reading the public [`microsoft/discovery-catalog`](https://github.com/microsoft/discovery-catalog) repository | Per your VS Code GitHub sign-in |

**Tokens are never written to disk by this extension.** They are obtained
on demand from VS Code's secure credential store, held in memory only for
the duration of an outbound HTTP request, and discarded. The in-memory
activity log explicitly excludes `Authorization` headers and never stores
raw bearer tokens.

The extension queries Microsoft Graph once per session to resolve the
signed-in user's display name (shown in the welcome banner). No other
identity data is retrieved.

## 3. Network endpoints

Every host the extension may contact, and what for:

| Host | Purpose | Auth |
|---|---|---|
| `management.azure.com` | Azure Resource Manager — list/read/create/delete resources in **your** subscription | Microsoft session token |
| `graph.microsoft.com` | Resolve your display name; verify the `AIFSPInfrastructure` service principal exists in your tenant (network-hardened workspaces only) | Microsoft session token |
| `*.azurecr.io` | Pull/push container images to **your** Azure Container Registry | ACR credentials sourced from ARM |
| `<workspace>.<region>.api.discovery.microsoft.com` (and similar) | Discovery workspace data plane — investigations, agents, conversations | Microsoft session token |
| `mcp.discovery.azure.com` (when MCP enabled) | Discovery MCP server for tool invocation | Microsoft session token |
| `learn.microsoft.com` | Open documentation links in your browser (no fetch from the extension) | None |
| `raw.githubusercontent.com/MicrosoftDocs/azure-docs/...` | Fetch Microsoft Discovery documentation pages for the in-extension Docs view | Anonymous HTTP GET |
| `api.github.com` / `raw.githubusercontent.com/microsoft/discovery-catalog` | Fetch the Discovery catalog (tool + agent definitions) | Your GitHub session token if you're signed in; anonymous (rate-limited) otherwise |
| `api.github.com/repos/microsoft/discovery/contents/utilities/discovery-toolbox/...` | Fetch the toolbox update manifest + new VSIX from the release folder | Your GitHub session token while the repo is private; anonymous once it goes public |

The extension does not contact any other host. It does not send error
reports, crash dumps, or "phone home" to any Microsoft or third-party
service.

## 4. Local files

The extension writes to two locations on your machine. Both are
user-purgeable: delete the directory and the data is gone.

### `~/.md-toolbox/`

Default location: `%USERPROFILE%\.md-toolbox\` (Windows),
`~/.md-toolbox/` (macOS / Linux).

| Subfolder | Contents |
|---|---|
| `deploys/*.jsonl` | One file per agent deploy. Stage logs (image build, ARM PUT, agent upsert), timings, resource IDs. Does **not** contain prompts. |
| `conversations/*.jsonl` | One file per conversation thread you've held with a deployed agent. **Includes the full text of every prompt you sent and every response the agent returned.** Includes workspace ARM id, project, investigation, conversation, and agent names. |
| `agent-scorecards/*.jsonl` | One file per scorecard run. **Includes the full prompt sent to each agent, the full response, the LLM judge's rationale, and the judge's confidence bucket.** Includes workspace ARM id, project, and agent names. |
| `validations/*.jsonl` | One file per validation run. Stage outcomes, timings, resource IDs, error messages. Does **not** contain prompts or agent responses. |
| `.cache/discovery-catalog/` | Cached copy of the public `microsoft/discovery-catalog` repository for offline use. |

You can delete any subfolder (or the whole `~/.md-toolbox/` directory) at
any time. The extension will recreate empty subfolders the next time the
relevant feature runs.

### OS temp directory

The extension stages Bicep parameter files and container build contexts
under your OS temp directory (`%TEMP%` / `/tmp`) for the duration of a
deploy. These are cleaned up by the OS automatically.

### VS Code workspace storage

Some user-interface preferences (drawer widths, dashboard layout) are
saved to VS Code's `localStorage`. No customer data is stored there.

## 5. AI calls (LLM judge in Agent Scorecard)

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

If you do not want this data sent to Copilot, do not run the Agent
Scorecard feature.

All other AI interactions (conversations on the Validation Interactions
page, MCP tool invocations) go **only** to the Discovery workspace you
deployed yourself, in your subscription, in your chosen Azure region.

## 6. Activity log

The "Activity Log" view shows the most recent ~500 HTTP requests and
actions the extension has performed in the current session. It is
in-memory only and is cleared when you reload the window. It is never
written to disk and never sent off the machine.

## 7. Personal data we never collect

To make this explicit: this extension does not collect, transmit, or
store:

- Your name, email, phone, address, or any contact information beyond
  the display name VS Code's auth provider already gives us
- Your IP address (the extension makes no calls that go to anything we
  control)
- Browser fingerprints, screen dimensions, OS version, or any device
  fingerprint
- Source code, file contents, or anything from your other VS Code
  workspaces
- Keystrokes outside the prompts you deliberately send to deployed
  agents (and even those stay in `~/.md-toolbox/conversations/` on your
  own machine)

## 8. How to remove all extension data

```bash
# All local artifacts (validation runs, conversations, scorecards, deploys, cache):
rm -rf ~/.md-toolbox

# VS Code-managed preferences (drawer widths etc.):
# Use VS Code's Command Palette: "Developer: Reload Window" then
# "Settings: Clear All" — or manually delete the extension's entry
# under your VS Code globalStorage path.

# Azure resources created by deploys:
# Use the Inventory → Tear down… action, or delete the resource group
# in the Azure portal.
```

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

<sub>Privacy notice for Discovery Toolbox **v1.1.67** · built from `d8bce6e` on 2026-06-01T18:47:30.060Z.</sub>

<sub>This document is maintained in the open in the [`microsoft/discovery`](https://github.com/microsoft/discovery/tree/main/utilities/discovery-toolbox) repository. It covers only this extension; for VS Code's own privacy practices see the [VS Code privacy statement](https://code.visualstudio.com/license).</sub>
