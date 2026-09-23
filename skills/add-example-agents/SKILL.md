---
name: add-example-agents
description: "Add agents from the public microsoft/discovery GitHub repository to this workspace, either (a) locally for the Copilot app by emitting a `.agent.md` companion per agent (so each is invocable via `runSubagent`), (b) into a Microsoft Discovery project via `UpsertAgent` sourced fresh from upstream (binding pre-existing tool ARM resources when present, or building + pushing + registering them in Azure first when missing), or (c) promoting an agent already added to the local Copilot app (sourced from its `.github/agents/<name>.agent.md` companion; tool-bearing agents also carry a `discovery_catalog/<name>/` folder plus a locally-built tool container, while toolless agents have only the companion) up to a specific Microsoft Discovery project + Azure without re-fetching or refreshing from upstream. The user picks exactly one of the three targets per run. USE FOR: 'add the discovery agents', 'download discovery agents', 'install all Microsoft discovery agents', 'add agents from microsoft/discovery', 'create copilot agents from microsoft/discovery', 'deploy discovery agents to Foundry', 'deploy discovery agents to Azure', 'promote a local agent to Microsoft Discovery', 'push my local agent and container to a Discovery project', 'copy a local app agent to Azure'. Always refreshes every selected subfolder under `agents/<name>/` of the upstream repo into `discovery_catalog/<name>/` so the local catalog stays current (new agents appear, removed agents are surfaced, updated content is applied). The presence check for what is 'already locally added' uses `.github/agents/<name>.agent.md` (the Copilot companion), not the `discovery_catalog/` folder. For local deployment, each generated `.agent.md` carries a lazy Docker-bootstrap preamble so the agent builds its tool image on first use only if absent. For Discovery + Azure deployment, pre-flights every declared tool via `GetDiscoveryTool` against the workspace's RG and **skips Docker build / ACR push / AcrPull RBAC entirely when the tool already exists** (common for shared catalog images on registries like `mdqacr`); only builds + registers tools that are actually missing. Always creates the agent in the chosen Discovery project via `UpsertAgent` and polls **`GetAgent` for `provisioningState=Succeeded`** (the MCP `GetAgentOperation` tool returns an opaque error in practice; never rely on it). All MCP calls flow through PowerShell scripts embedded in this SKILL.md and materialized into `.vscode/` during Step 4d — the skill does not depend on sibling helper files or on the VS Code MCP runtime surfacing `mcp_microsoft-dis_*` tools mid-session. Local Discovery runtime registration via `agents action=create` is optional and skipped by default. DO NOT USE FOR: running an already-deployed agent (use runSubagent), or editing a single agent's prompt (edit `agent.yaml` directly)."
license: MIT
metadata:
  author: Internal
  version: "1.16.0"
  changelog:
    - "1.16.0: LocalToDiscovery promote now sources the agent `name` and `description` from the .github/agents/<name>.agent.md companion frontmatter (same source of truth as `instructions`), NOT from discovery_catalog/<name>/agent.yaml, for BOTH tool-bearing and toolless agents. Added Get-AgentMdFrontmatterValue helper (Step 4c.LTD), updated the 4c.LTD classification, Step 7e.1 field sourcing + code, Step 7e.4 description bullet, and the Step 7g guard-rail. Description is still truncated to the 512-char Foundry cap; falls back to agent.yaml#description only when the companion has none."
    - "1.15.0: Fixed a CRLF line-ending bug that produced a truncated (~369-char) instructions body on Windows companions. Get-AgentMdInstructions and Convert-PromoteInstructionsForTool now use '\\r?\\n---\\r?\\n' (not '\\n---\\n') for the bootstrap horizontal-rule delimiter — a bare '\\n---\\n' never matches a CRLF companion, so the '|\\z' fallback in Convert previously swallowed the whole prompt. Added a Step 7e.1 length sanity-check (throw if <500 chars). Hardened Step 7e.4 description sourcing with the 512-char Foundry cap (bare Failed / foundryDetails=null is a description-length problem, not tool-binding). Added Step 7c guidance: a previously-deployed tool ARM can be deleted (404) while its image survives in ACR — check 'az acr repository show-tags' and re-register the tool ARM without rebuilding when the image is present."
    - "1.14.0: LocalToDiscovery promote now rewrites tool-bearing agents' cloud instructions to reference the deployed Discovery tool instead of a local Podman/Docker image. Added Convert-PromoteInstructionsForTool (Step 4c.LTD) which strips the container bootstrap preamble, scrubs residual podman/docker build/pull/push/image-inspect lines and discovery_catalog/.../tools/... build-context references, and appends a 'Tool execution (Microsoft Discovery)' note naming the deployed tool(s). Step 7e.1 applies it for $agentHasCatalogFolder agents and requires each declared tool to be provisioningState=Succeeded with its image in the workspace ACR before UpsertAgent. Added a Step 7g guard-rail."
    - "1.13.0: LocalToDiscovery (promote) now sources the agent picker from .github/agents/*.agent.md (the local-app companions) instead of requiring a discovery_catalog/<name>/ folder. Agents are classified into tool-bearing (has discovery_catalog folder + agent.yaml + tools) vs toolless (companion only, created locally with no container tool). Toolless agents skip Step 7c/7d entirely and get instructions from the .agent.md body (frontmatter for name/description, body minus the container-bootstrap preamble for instructions) with an empty toolIds. Added Get-AgentMdInstructions helper, $agentHasCatalogFolder classification, and relaxed the 7g 'source of truth' guard-rail so a missing discovery_catalog folder is valid for toolless promotes."
    - "1.12.0: Hardened the Discovery deploy path from a real promotion run. Tool ARM registration now requires properties.definitionContent to be a JSON object built with [ordered]@{} (raw tool.yaml string fails InvalidType) and passes the body via a temp file with --body @file. code_environments[].language must be normalized to python3 (python passes the tool PUT but breaks Foundry agent-binding with a bare Failed). Added az acr build Windows console UnicodeEncodeError guidance (set PYTHONIOENCODING=utf-8; poll az acr task list-runs instead of rebuilding). Added Step 7e recovery flow for fast tool-binding failures: isolate prompt vs tool by upserting without toolIds, fix language, wait ~30-60s for Foundry propagation before rebinding, and use GetAgentOperation (operationId) to extract the real error when GetAgent reports a bare Failed."
    - "1.11.0: Added a third deployment target (LocalToDiscovery) that promotes an agent already added to the local Copilot app — its local discovery_catalog/<name>/ folder and locally-built tool container — up to a specific Microsoft Discovery project + Azure without re-fetching or refreshing from upstream. Source of truth is the local folder; tool images are pushed from the local build context or the locally-built image. Added $deployToCloud / $sourceMode helper flags, Step 4c.LTD (local catalog index), Step 5 skip for the local source, and Step 7d.LTD (push local image)."
    - "1.10.1: Hardened local generation: require temp .ps1 execution for multi-line scripts, fix .agent.md stem detection, parse YAML block-scalar descriptions correctly, and write generated .agent.md files with read/write sharing to avoid transient editor locks."
    - "1.10.0: Changed upstream source from private microsoft/discovery-catalog agents/microsoft/ to public microsoft/discovery agents/, removing GitHub authentication requirements."
    - "1.9.0: Added Local runtime selection flow (Podman/Docker detection, defaulting, optional Podman auto-install) and changed generated .agent.md bootstrap instructions to try Podman first then Docker as fallback."
    - "1.8.0: Embedded discovery-mcp-proxy.ps1 and Invoke-DiscoveryMcp.ps1 directly in SKILL.md and changed Step 4d/7a to extract them into .vscode, so the skill can be distributed as one file."
    - "1.7.0: Co-located proxy + Invoke-DiscoveryMcp helper as sibling files. Made scripted stdio invocation the canonical MCP path (no longer depends on VS Code surfacing mcp_microsoft-dis_* tools mid-session). Replaced GetAgentOperation polling with GetAgent provisioningState polling. Bumped ARM api-version to 2026-06-01. Added explicit 'agents are NOT an ARM resource type' callout."
---

# add-example-agents

Add agents from the public `microsoft/discovery` repository to this
workspace, then deploy each selected agent to exactly one of two targets:

- **Local Copilot** - emit a `.github/agents/<name>.agent.md` companion for
  every agent so it can be invoked as a Copilot subagent via `runSubagent`.
  Tool container images are built lazily on first invocation, locally only.
- **Microsoft Discovery + Azure** - pre-flight every tool the agent
  declares via `GetDiscoveryTool` against the workspace's RG. When a tool
  ARM resource already exists (common for shared catalog images on
  registries like `mdqacr`), skip Docker build / ACR push / AcrPull RBAC
  entirely and bind the existing ARM ID. When a tool is missing, build +
  push via `az acr build`, register the tool ARM, grant AcrPull. Either
  way, create the agent in the target Discovery project via `UpsertAgent`
  and poll **`GetAgent`** until `provisioningState=Succeeded`. Local
  Discovery runtime registration (`agents action=create`) is optional and
  skipped by default.
- **Local app → Microsoft Discovery + Azure (promote)** - take an agent
  that is **already added to the local Copilot app** (present under
  `discovery_catalog/<name>/` with a `.github/agents/<name>.agent.md`
  companion and, for tool-bearing agents, a locally-built container image)
  and register it in a specific Discovery project. The **local** folder is
  the source of truth - the upstream `microsoft/discovery` repo is **not**
  fetched or refreshed, so any local edits are preserved. Tool container(s)
  are pushed to ACR from the local build context / locally-built image, then
  the agent is created via `UpsertAgent` and polled with `GetAgent` exactly
  as in the upstream-sourced Discovery path.

The user picks the deployment target **first** (Step 4c), then — only for a Discovery-class target (Discovery or LocalToDiscovery) — confirms the destination workspace + project (Step 4d), and **then** chooses which agents to add (Step 4e).

## Source of truth

- Upstream repo: `https://github.com/microsoft/discovery`
- Path of interest: `agents/`
- Each subfolder under `agents/<NAME>/` is one Discovery agent.

The upstream layout for every agent is identical and matches what already lives
in this workspace's `discovery_catalog/`:

```
agents/<name>/
├── agent.yaml          # prompt / hosted agent definition (kind: prompt)
├── metadata.yaml       # name, version, associated_tools, publisher, tags
├── README.md           # deployment & usage guide
└── tools/
    └── <ToolName>/
        ├── Dockerfile          # container image recipe
        ├── tool.yaml           # tool definition (infra, code_environments)
        ├── *-EnvVars.json      # optional env-var spec
        ├── basic-description.txt
        └── <utils>.py          # optional helper code
```

The local target is **identical**, only the parent folder differs:

```
discovery_catalog/<name>/...    # 1:1 mirror of agents/<name>/...
```

So adding an agent is a straight folder copy — no transformation required.

## Prerequisites

Required for **every** run (Step 3 — fetch catalog):

| Requirement | Check command | Required for |
|---|---|---|
| `git` on PATH | `git --version` | cloning the catalog |
| Network access to github.com | `Test-NetConnection github.com -Port 443` | cloning |

Required **only** when `$deployToCloud` is true (`$deployTarget` is `Discovery` or `LocalToDiscovery`) (Step 7 —
Microsoft Discovery + Azure deployment):

| Requirement | Check command | Required for |
|---|---|---|
| `az` CLI on PATH | `az --version` | Azure subscription / ACR / RBAC operations (fallback when Azure MCP is absent) |
| Active `az login` session | `az account show` | calling any Azure resource |
| `docker` CLI on PATH | `docker --version` | building tool images locally before push (fallback when Azure MCP / `az acr build` is unavailable) |
| Azure Container Registry write access | `az acr login -n <acr>` | pushing tool images |
| Discovery MCP reachable via the proxy | `pwsh -NoProfile -File .vscode/discovery-mcp-proxy.ps1` accepts a JSON-RPC `initialize` and replies | tool pre-flight (`GetDiscoveryTool`), agent provisioning (`UpsertAgent` + `GetAgent` poll), model lookup (`ListChatModelDeployments`). Installed by Step 4d by extracting the embedded `discovery-mcp-proxy.ps1` and `Invoke-DiscoveryMcp.ps1` blocks from this `SKILL.md` into `.vscode/`. **All MCP calls go through the extracted proxy via the extracted `Invoke-DiscoveryMcp` helper, not through VS Code's `mcp_microsoft-dis_*` deferred tools.** The mcp.json registration is written too, but only as a courtesy for the user's future interactive sessions — never wait for those deferred tools to surface mid-run. |
| `microsoft-foundry` skill (optional) | (listed in workspace skills) | reference only — **not** invoked via `runSubagent`. Catalog agents are not azd projects, so the foundry skill's `.foundry/` overlay flow does not apply. Use the direct Discovery MCP path documented in Steps 7c–7e. |

The upstream repository is public. Do not require `gh`, `GH_TOKEN`,
`GITHUB_TOKEN`, GitHub device-flow login, or any other GitHub authentication
for the catalog fetch. Anonymous `git clone` and GitHub contents API requests
are expected to work.

When `$deployTarget == 'Local'`, neither Docker Desktop nor Podman is a hard
prerequisite for running this skill itself. The skill never invokes local
image builds directly; image bootstrap is delegated to each generated agent at
invocation time (see Step 6). Runtime readiness is handled by Step 4f.

## Scripted MCP invocation (canonical fast path)

> **This is the only MCP path the skill should use mid-run.** Do NOT wait
> for VS Code's MCP runtime to surface `mcp_microsoft-dis_*` deferred
> tools — in practice they often do not appear in the same session that
> registered them. Invoke the proxy directly via stdio instead. It works
> first-try every time once `az login` is set up.

Two PowerShell files are embedded at the bottom of this skill and materialized
into `.vscode/` during Step 4d:

| Embedded block | Role |
|---|---|
| `embedded-discovery-mcp-proxy.ps1` | Local PowerShell stdio ↔ HTTPS proxy. Mints `https://discovery.azure.com` tokens via `az`, forwards JSON-RPC frames to `https://mcp.discovery.azure.com/mcp`, refreshes on 401, preserves `Mcp-Session-Id`. |
| `embedded-Invoke-DiscoveryMcp.ps1` | PowerShell helpers: `Invoke-DiscoveryMcp` (spawn proxy, send initialize + N `tools/call`, return responses keyed by JSON-RPC id), `Get-DiscoveryMcpText` (extract / parse the text payload), `Wait-DiscoveryAgentReady` (poll `GetAgent` for `provisioningState=Succeeded`). |

**Install ritual (run once per workspace, in Step 4d):**

```pwsh
$skillDir = "<absolute path to this skill folder>"   # contains SKILL.md
New-Item -ItemType Directory -Force -Path "$workspaceRoot\.vscode" | Out-Null
$skillPath = Join-Path $skillDir 'SKILL.md'
$skillText = Get-Content $skillPath -Raw
function Write-EmbeddedSkillScript([string]$BlockId, [string]$Destination) {
  $begin = "<!-- BEGIN:$BlockId -->"
  $end = "<!-- END:$BlockId -->"
  $start = $skillText.IndexOf($begin)
  if ($start -lt 0) { throw "Embedded script block '$BlockId' not found in $skillPath" }
  $contentStart = $start + $begin.Length
  $stop = $skillText.IndexOf($end, $contentStart)
  if ($stop -lt 0) { throw "Embedded script block '$BlockId' has no end marker in $skillPath" }
  $block = $skillText.Substring($contentStart, $stop - $contentStart).Trim()
  $lines = @($block -split "`r?`n")
  if ($lines.Count -lt 3 -or $lines[0] -notmatch '^```powershell\s*$' -or $lines[-1] -notmatch '^```\s*$') {
      throw "Embedded script block '$BlockId' must be wrapped in a powershell fenced code block."
  }
  $content = (($lines[1..($lines.Count - 2)]) -join "`r`n") + "`r`n"
  Set-Content -Path $Destination -Value $content -Encoding UTF8
}
Write-EmbeddedSkillScript 'embedded-discovery-mcp-proxy.ps1' "$workspaceRoot\.vscode\discovery-mcp-proxy.ps1"
Write-EmbeddedSkillScript 'embedded-Invoke-DiscoveryMcp.ps1' "$workspaceRoot\.vscode\Invoke-DiscoveryMcp.ps1"

# (Optional, for the user's future interactive sessions only) write .vscode/mcp.json
# — see Step 7a.2 for the merge-safe writer. Do NOT block on the MCP runtime
# actually loading those tools mid-run.
```

**Canonical call pattern (use this for ListWorkspaces / ListProjects /
ListAgents / GetDiscoveryTool / ListChatModelDeployments / UpsertAgent /
GetAgent — every MCP call this skill makes):**

```pwsh
. "$workspaceRoot\.vscode\Invoke-DiscoveryMcp.ps1"
$proxy = "$workspaceRoot\.vscode\discovery-mcp-proxy.ps1"

$results = Invoke-DiscoveryMcp -ProxyPath $proxy -Calls @(
    @{ name='ListAgents'; args=@{
        subscriptionId    = $sub
        resourceGroupName = $rg
        workspaceName     = $ws
        projectName       = $proj
    } }
)
$obj = Get-DiscoveryMcpText -Response $results['2'] -AsJson
# $obj is the parsed payload (varies by tool — array, {value:[]}, single object, …)
```

**Polling pattern for `UpsertAgent` completion** — for the happy path,
prefer `GetAgent` provisioningState polling over `GetAgentOperation`
(historically `GetAgentOperation` has sometimes returned an opaque
`"An error occurred invoking 'GetAgentOperation'."`). Use the provided
helper. When `GetAgent` reports a bare `Failed` with no error text,
`GetAgentOperation` (called with the `UpsertAgent` operationId) *can*
return the real `{status, error, result}` — see Step 7e.5:

```pwsh
Wait-DiscoveryAgentReady -ProxyPath $proxy `
    -SubscriptionId $sub -ResourceGroupName $rg `
    -WorkspaceName $ws -ProjectName $proj `
    -AgentName 'retrochimera' -TimeoutSeconds 300
```

**Why scripts, not inline heredocs.** The VS Code agent terminal echoes
multi-line PowerShell commands back to stdin and frequently truncates
heredocs. **Always** write multi-line PowerShell to a temp `.ps1` file
(`"$env:TEMP\dc-<task>.ps1"`) and invoke with
`pwsh -NoProfile -File "<path>"`. One-liners are fine. This applies to
the Step 6 local companion-generation script as well as MCP scripts. Do
not paste a long function-heavy PowerShell block directly into the shared
terminal; if a prompt is left inside a partial function or here-doc, close
that syntax first and rerun from a `.ps1` file.

**Operational guarantees:**

- Agents are **not** an ARM resource type. There is no
  `Microsoft.Discovery/workspaces/projects/agents` resource provider.
  Never call `az rest .../projects/<p>/agents?...` — it always returns
  `ResourceTypeRegistrationNotFound`. Agents only exist behind the MCP
  server's `ListAgents` / `GetAgent` / `UpsertAgent` / `DeleteAgent`.
- Workspaces and projects **are** ARM resources but use the
  `Microsoft.Discovery` provider — current api-version `2026-06-01`
  (older `2024-10-01-preview` is rejected with
  `InvalidResourceType`). Prefer the MCP `ListWorkspaces` /
  `ListProjects` calls anyway — they return the same data without
  api-version drift.
- `Microsoft-dis_*` deferred tool names are **not** required. If a
  later VS Code release surfaces them automatically, the skill may use
  them in addition to the proxy — but never instead of it (the proxy
  is the always-available baseline).

## Workflow

### Step 1 — Discover workspace layout

1. Locate the workspace root by searching for a top-level `discovery_catalog/`
   folder (the user's prompt may not say where it is).
2. Enumerate **`.github/agents/*.agent.md`** — these are the Copilot companion
   files and are the **authoritative source of truth for which agents are
   already locally added**. Strip the `.agent.md` suffix to get the agent
   folder name. Use this set (call it `$existingLocalAgents`) for both the
   Step 4e Local collision hint and the Step 8 "already had companion"
   summary bucket. **Do not** infer "already added" from the presence of a
   `discovery_catalog/<name>/` folder — that folder is always refreshed from
   upstream in Step 5 and would mislabel every entry as "already present".
     In PowerShell, do **not** use `$_.BaseName` for this; for
     `pubchem.agent.md`, `.BaseName` is `pubchem.agent`, not `pubchem`.
     Use an explicit suffix removal:
     ```pwsh
     $existingLocalAgents = @{}
     Get-ChildItem $agentsDir -Filter '*.agent.md' -File -ErrorAction SilentlyContinue | ForEach-Object {
       $stem = $_.Name -replace '\.agent\.md$', ''
       $existingLocalAgents[$stem] = $true
     }
     ```
3. Also list the `discovery_catalog/<name>/` folders so Step 5 can report
   which folders were **created fresh** vs **refreshed in place** vs
   **removed from upstream** (no longer present in `agents/`).

### Step 2 — Confirm public GitHub access

> **Skip Steps 2 and 3 when `$deployTarget == 'LocalToDiscovery'`**
> (`$sourceMode == 'Local'`). Promotion never touches the upstream repo — the
> agent already lives in `discovery_catalog/`. When the user's request clearly
> asks to promote a local agent, ask the Step 4c deployment-target question
> **before** these steps so the fetch is avoided; otherwise a fetch that
> already ran is simply ignored (the clone is discarded in Step 8). Build the
> catalog index from the local workspace instead (Step 4c.LTD).

The `microsoft/discovery` repo is public. Do **not** run `gh auth status`,
`gh auth login`, token setup, or authenticated REST probes for the catalog.
Only verify ordinary network access to GitHub before cloning:

```pwsh
git --version
Test-NetConnection github.com -Port 443
```

If the public fetch returns 404 or another HTTP error, report the exact
command + status / git error. Treat it as a network, URL, rate-limit, or
temporary GitHub availability problem unless the user provides different
evidence. **Never fabricate agent content.**

### Step 3 — Fetch the upstream catalog

Prefer a shallow sparse checkout to avoid pulling unrelated parts of the repo:

```pwsh
$work = Join-Path $env:TEMP ("discovery-agents-" + [Guid]::NewGuid().ToString('N').Substring(0,8))
git clone --depth 1 --filter=blob:none --sparse https://github.com/microsoft/discovery.git $work
Push-Location $work
git sparse-checkout set agents
Pop-Location
```

Fallbacks (in order) if the sparse clone fails:

1. `git clone --depth 1 https://github.com/microsoft/discovery.git $work`
2. REST API: enumerate
   `https://api.github.com/repos/microsoft/discovery/contents/agents`
   recursively, downloading each file with
  `Invoke-WebRequest -Headers @{ 'User-Agent' = 'add-agent-from-catalog' }`.

If all fetch strategies fail, stop and report the exact command + HTTP status /
git error. **Never fabricate agent content.**

### Step 4 — Pick deployment target, confirm workspace/project, then choose agents

Ask the user **the required prompts in this order**, via `vscode_askQuestions`.
Never copy the entire catalog silently — many agents are heavyweight (container
tools, large research stacks) and the user should opt in.

1. **Deployment target** (Step 4c) — Local Copilot only / Microsoft Discovery + Azure (from upstream) / Local app -> Microsoft Discovery + Azure (promote).
2. **Discovery workspace + project** (Step 4d, conditional on a Discovery-class target — `Discovery` or `LocalToDiscovery`) —
   ensure the user is signed in to Azure, install the Discovery MCP if missing,
   list available workspaces and projects, list existing agents in the chosen
   project, and confirm the destination. This MUST happen **before** the agent
   picker so the user can see name collisions in the target project.
3. **Agent selection** (Step 4e) — selection mode (All / Specific / By group)
   plus values.

Steps 4a and 4b (build catalog index + derive groups) still run before the
agent picker in Step 4e, but they don't require user input and can happen at
any point after Step 3 (catalog fetch).

#### 4a. Build the catalog index

For each `agents/<name>/` folder under the freshly-cloned `$srcRoot`,
read `metadata.yaml` and extract:

- `name` (fallback: folder name)
- `tags` (list — may be empty)
- `description` from `agent.yaml` (first sentence, trimmed to ~80 chars for display)
- `associated_tools` count (from `metadata.yaml`, used to flag heavyweight agents)

```pwsh
$srcRoot = Join-Path $work 'agents'
$catalog = @()
Get-ChildItem $srcRoot -Directory | ForEach-Object {
    $folder = $_.Name
    $meta   = Join-Path $_.FullName 'metadata.yaml'
    $ay     = Join-Path $_.FullName 'agent.yaml'
    $tags   = @()
    $tools  = 0
    $desc   = ''
    if (Test-Path $meta) {
        $mtxt = Get-Content $meta -Raw
        # Extract tags: lines like "  - tagname" under a "tags:" key
        if ($mtxt -match '(?ms)^tags:\s*\r?\n((?:\s*-\s*\S+\r?\n?)+)') {
            $tags = ($matches[1] -split "`n") |
                ForEach-Object { ($_ -replace '^\s*-\s*', '').Trim() } |
                Where-Object { $_ }
        }
        if ($mtxt -match '(?ms)^associated_tools:\s*\r?\n((?:\s*-\s*\S+\r?\n?)+)') {
            $tools = (($matches[1] -split "`n") | Where-Object { $_ -match '\S' }).Count
        }
    }
    if (Test-Path $ay) {
        $atxt = Get-Content $ay -Raw
        if ($atxt -match '(?ms)^description:\s*[>|]?\s*\r?\n((?:\s{2,}.+\r?\n?)+)') {
            $desc = (($matches[1] -split "`n")[0] -replace '^\s+', '').Trim()
        } elseif ($atxt -match '^description:\s*(.+)$') {
            $desc = $matches[1].Trim().Trim('"').Trim("'")
        }
    }
    $catalog += [pscustomobject]@{
        Folder = $folder
        Tags   = $tags
        Tools  = $tools
        Desc   = $desc
    }
}
```

#### 4b. Derive groups

Group agents by their tags. An agent with multiple tags appears in each
matching group. Always include two synthetic groups at the top:

- **All agents** — every folder under upstream `agents/`.
- **Lightweight (no container tools)** — agents whose `tools/` folder is empty or
  contains no `Dockerfile`. These install fastest and don't require local
  container runtimes.

```pwsh
$groups = [ordered]@{}
$groups['All agents']                = $catalog.Folder
$groups['Lightweight (no container tools)'] = ($catalog | Where-Object { $_.Tools -eq 0 }).Folder
foreach ($a in $catalog) {
    foreach ($t in $a.Tags) {
        if (-not $groups.Contains($t)) { $groups[$t] = @() }
        $groups[$t] += $a.Folder
    }
}
# Deduplicate
foreach ($k in @($groups.Keys)) { $groups[$k] = $groups[$k] | Select-Object -Unique }
```

#### 4c. Ask deployment target (FIRST user-facing prompt)

Single `vscode_askQuestions` call with one question. This MUST be asked
before workspace/project (4d) or agent selection (4e) - the answer
determines whether 4d runs at all and changes what 4e shows.

```
header: "deployment-target"
question: "Where do you want these agents deployed?"
options:
  - "Microsoft Discovery local app only" (recommended default - requires a GitHub Copilot license, no Azure subscription needed)
  - "Microsoft Discovery service (from upstream)" (Azure subscription required, fetches each agent fresh from microsoft/discovery and registers it in a specific Discovery workspace project that you select)
  - "Promote a local app agent to Microsoft Discovery service" (Azure subscription required, takes an agent already added to the local app plus its locally-built tool container and registers it in a specific Discovery workspace project that you select, without re-fetching upstream)
```

Persist as `$deployTarget` (`Local` | `Discovery` | `LocalToDiscovery`):

- `Local`            - refresh `discovery_catalog/` from upstream and emit
                     `.github/agents/*.agent.md` (Steps 5 + 6). Local tool
                     images are built lazily on first invocation only, via
                     Podman-first then Docker fallback.
- `Discovery`        - refresh `discovery_catalog/` from upstream, build + push
                     any missing tool images to ACR, register each agent in the
                     Microsoft Discovery project via `UpsertAgent` (Steps 5 + 7).
- `LocalToDiscovery` - **do not fetch or refresh from upstream**; use the
                     agent's existing local `discovery_catalog/<name>/` folder
                     as the source of truth. Build + push any missing tool
                     images to ACR from the local build context / locally-built
                     image, then register the agent in the Microsoft Discovery
                     project via `UpsertAgent` (Step 7; local-source deltas in
                     Steps 4c.LTD and 7d.LTD).

Derive two helper flags used throughout the rest of the workflow:

- `$deployToCloud = $deployTarget -in @('Discovery','LocalToDiscovery')` -
  true for both Discovery-class targets. **Wherever a later step gates on
  `$deployTarget == 'Discovery'` for Azure/Discovery work (Steps 4d, 7 and
  all its sub-steps, and the Discovery branches of Step 8), read it as
  `$deployToCloud`** so the promote target runs the same cloud machinery.
- `$sourceMode = if ($deployTarget -eq 'LocalToDiscovery') { 'Local' } else { 'Upstream' }` -
  `Upstream` fetches + refreshes from `microsoft/discovery` (Steps 2, 3, 5);
  `Local` skips all upstream fetch/refresh and treats
  `discovery_catalog/<name>/` as authoritative.

Step 5 runs for `Upstream` source mode only. For `LocalToDiscovery`
(`$sourceMode == 'Local'`) it is **skipped** - overwriting the local folder
with upstream would discard the local edits the user is promoting.

Downstream branch:

- `Local`     \u2192 skip 4d. Run 4e (agent picker), then 4f (local runtime
          readiness), then Step 6.
- `Discovery` \u2192 run 4d **immediately** (workspace + project picker, before
              the agent picker). Then run 4e, then Step 7.
- `LocalToDiscovery` -> skip the upstream fetch (Steps 2 + 3); build the catalog
              index from the local `.github/agents/` companions (Step 4c.LTD),
              classifying each into tool-bearing (has `discovery_catalog/<name>/`)
              vs toolless; run 4d **immediately** (workspace + project picker);
              then run 4e (agent picker scoped to the local-app companions in
              `$localAgents`); **skip Step 5**; then run Step 7.

#### 4c.LTD. Build the catalog index from the local app (LocalToDiscovery only)

Run this **instead of** the upstream fetch (Steps 2 + 3) and the upstream
catalog index (Step 4a) when `$deployTarget == 'LocalToDiscovery'`. The
source of truth is the workspace, not `microsoft/discovery`.

**The authoritative list of what can be promoted is
`.github/agents/*.agent.md` (the `$existingLocalAgents` set from Step 1),
NOT the `discovery_catalog/` folders.** A locally-created agent may have
**no** `discovery_catalog/<name>/` folder at all — that folder only exists
for agents that carry a container-based tool. A toolless prompt agent lives
entirely in its `.github/agents/<name>.agent.md` companion. Both kinds are
promotable; only the source of `agent.yaml`-equivalent fields differs.

Classify each companion in `$existingLocalAgents` into one of two buckets:

- **Tool-bearing** — a `discovery_catalog/<name>/` folder exists with an
  `agent.yaml`. Read `metadata.yaml#associated_tools` and the
  `tools/<Tool>/` subtree from there. Source **both** `instructions` **and**
  `name` / `description` from the `.github/agents/<name>.agent.md` companion
  (via `Get-AgentMdInstructions` and `Get-AgentMdFrontmatterValue`),
  **not** from `agent.yaml` — the companion is the source of truth for the
  prompt body *and* the display name/description the user tuned locally
  (see Step 7e.1). These go through the full Step 7 tool
  pre-flight / build / bind path.
- **Toolless** — no `discovery_catalog/<name>/` folder (or the folder has
  no `agent.yaml`). Source the agent fields from the `.agent.md` companion
  instead: `name` and `description` from its YAML frontmatter (via
  `Get-AgentMdFrontmatterValue`), and the `instructions` from its markdown
  body (strip any auto-generated "Container image bootstrap" preamble and
  the leading `---` frontmatter block; what remains is the Discovery
  prompt). These skip all of Step 7c/7d (no tools) and go straight to
  `UpsertAgent` in Step 7e with an empty `toolIds`.

Steps:

1. Enumerate promotable agents = every stem in `$existingLocalAgents`
   (the `.github/agents/<name>.agent.md` companions). Persist as
   `$localAgents`. For each, record `$agentHasCatalogFolder[$name]` =
   `Test-Path discovery_catalog/<name>/agent.yaml`. Do **not** require a
   `discovery_catalog/` folder — its absence just means "toolless".
   **Exclude the hand-authored, non-Discovery Copilot agents** that ship
   with the workspace and are not catalog/Discovery agents — at minimum
   `batteries-included`, `bookshelf-researcher`, `project-setup-orchestrator`,
   and `agentic-grader`. A companion qualifies as promotable only if it was
   produced by this skill (Local target, Step 6) or otherwise represents a
   Discovery agent; if unsure, prefer companions whose body contains the
   generated container-bootstrap preamble or that have a matching
   `discovery_catalog/<name>/` folder, and skip the rest.
2. If `$localAgents` is empty, stop and tell the user there are no
   locally-added agents to promote — they must first add one via the
   **Local Copilot** target, then re-run for promotion.
3. Build the same `$catalog` / `$groups` structures Steps 4a/4b produce.
   For **tool-bearing** agents read `metadata.yaml` / `agent.yaml` from
   `discovery_catalog/<name>/`; for **toolless** agents read `name` /
   `description` from the `.agent.md` frontmatter and set the tool count to
   `0` (they always land in the *Lightweight (no container tools)* group).
   Do not set a single `$srcRoot` for tool enumeration — resolve each
   agent's source per-bucket via `$agentHasCatalogFolder` so Step 7 reads
   from the right place.
4. In Step 4e, scope the agent picker to `$localAgents` only (label each
   `[agent] <name>`), and drop the "upstream refresh" framing — nothing is
   fetched or overwritten. Optionally annotate toolless entries in the
   option `description` with `(no container tool)` so the user can tell them
   apart from tool-bearing ones.

   ```pwsh
   # Extract the promotable instructions from a toolless .agent.md companion.
   #
   # CRLF-SAFE: generated .agent.md companions are written with CRLF line
   # endings on Windows. A naive `\n---\n` horizontal-rule match FAILS to
   # match (the real bytes are `\r\n---\r\n`), so the bootstrap strip below
   # would silently no-op and leave the whole preamble in the body. ALWAYS
   # use `\r?\n---\r?\n` for the horizontal-rule delimiter.
   function Get-AgentMdInstructions([string]$AgentMdPath) {
     $raw = Get-Content $AgentMdPath -Raw
     # Drop the leading YAML frontmatter block ( --- ... --- ).
     $body = $raw -replace '(?s)^\s*---.*?---\s*', ''
     # Drop an auto-generated container-bootstrap preamble, if present:
     # everything up to and including the first '---' horizontal rule that
     # the generator emits after the preamble table.
     if ($body -match '(?s)^\s*#\s*Container image bootstrap.*?\r?\n---\r?\n') {
       $body = $body -replace '(?s)^\s*#\s*Container image bootstrap.*?\r?\n---\r?\n', ''
     }
     return $body.Trim()
   }
   ```

   > **CRLF gotcha (verified in a real run).** If you write these regexes
   > with a bare `\n---\n` instead of `\r?\n---\r?\n`, a CRLF-terminated
   > companion produces a **tiny** instructions body — in one run just the
   > appended "## Tool execution" note (~369 chars) instead of the real
   > ~13k-char prompt. After extraction, **sanity-check the length**: a
   > tool-bearing agent's instructions should be thousands of characters.
   > If `Get-AgentMdInstructions` returns only a few hundred chars, the
   > CRLF bug bit you — fix the regex and re-extract before `UpsertAgent`.

   **The `.agent.md` companion is also the source of truth for `name` and
   `description`** — not just `instructions`. Use this helper to read a
   scalar value from the companion's YAML frontmatter (the block between the
   leading `---` fences). It handles both inline (`description: "..."`) and
   the escaped double-quoted form the Step 6 generator emits. Apply it for
   **both** tool-bearing and toolless promotes so the deployed Discovery
   agent's `name` / `description` match exactly what the user tuned locally.

   ```pwsh
   # Read a single scalar key from the .agent.md YAML frontmatter block.
   # CRLF-safe. Returns '' if the key is absent.
   function Get-AgentMdFrontmatterValue([string]$AgentMdPath, [string]$Key) {
     $raw = Get-Content $AgentMdPath -Raw
     # Isolate the leading frontmatter block ( --- ... --- ).
     if ($raw -notmatch '(?s)^\s*---\r?\n(.*?)\r?\n---\r?\n') { return '' }
     $fm = $matches[1]
     foreach ($line in ($fm -split "`r?`n")) {
       if ($line -match ("^" + [regex]::Escape($Key) + ":\s*(.+)$")) {
         $v = $matches[1].Trim()
         # Strip surrounding quotes and unescape \" and \\ from the
         # double-quoted frontmatter the generator writes.
         if ($v.StartsWith('"') -and $v.EndsWith('"') -and $v.Length -ge 2) {
           $v = $v.Substring(1, $v.Length - 2) -replace '\\"', '"' -replace '\\\\', '\'
         } elseif ($v.StartsWith("'") -and $v.EndsWith("'") -and $v.Length -ge 2) {
           $v = $v.Substring(1, $v.Length - 2)
         }
         return $v.Trim()
       }
     }
     return ''
   }
   ```

##### Rewriting local container references for tool-bearing promotes

A **tool-bearing** local agent's `.agent.md` companion (and, in rare
hand-edited cases, its `agent.yaml#instructions`) can reference the tool as
a **local** Podman/Docker container image — e.g. "build `<tool>:latest` from
`discovery_catalog/<name>/tools/<Tool>`", "`podman image inspect`",
"`docker build -t ...`". Those references are **local-only** and are
meaningless in the cloud, where the tool runs as a deployed
`Microsoft.Discovery/tools` ARM resource backed by an image in the
workspace's Azure Container Registry.

When promoting a tool-bearing agent (Step 7), **do not** deploy the local
container-runtime wording. Instead:

1. Strip the auto-generated bootstrap preamble (already done by
   `Get-AgentMdInstructions`).
2. Scrub any **residual** local-runtime references that survive in the body
   (stray `podman`/`docker` `build|pull|push|image inspect` lines, or lines
   that point at a `discovery_catalog/.../tools/...` build context).
3. Rewrite the tool reference so the cloud instructions point at the
   **Discovery tool** by name — the one found under
   `discovery_catalog/<name>/tools/<Tool>/` and registered as an ARM
   resource in Step 7c/7d — not at any local image tag or build context.

Use this helper (defined alongside `Get-AgentMdInstructions`) to produce
the cloud instructions for tool-bearing agents:

```pwsh
# Rewrite local Podman/Docker container references in a tool-bearing agent's
# promoted instructions so the cloud prompt references the deployed Discovery
# tool(s) instead of a local image tag / build context.
function Convert-PromoteInstructionsForTool {
  param(
    [Parameter(Mandatory)][string]$Instructions,
    [Parameter(Mandatory)][string[]]$ToolNames
  )
  $text = $Instructions

  # 1. Remove any lingering container-runtime bootstrap section (defense in
  #    depth — Get-AgentMdInstructions normally already removed it).
  #    CRLF-SAFE: use `\r?\n---\r?\n` for the horizontal-rule delimiter.
  #    A bare `\n---\n` never matches a CRLF companion, so the `|\z`
  #    fallback would then swallow the ENTIRE body (deleting the real
  #    prompt and leaving only the appended note). Never use `\n---\n` here.
  $text = $text -replace '(?s)#\s*Container image bootstrap.*?(\r?\n---\r?\n|\z)', ''

  # 2. Drop stray local-runtime instruction lines that reference building /
  #    inspecting / pulling / pushing a local image or a local build context.
  $lines = $text -split "`r?`n"
  $kept = foreach ($ln in $lines) {
    if ($ln -match '(?i)\b(podman|docker)\b.*\b(build|pull|push|image\s+inspect|info)\b') { continue }
    if ($ln -match '(?i)discovery_catalog/[^`\s]+/tools/') { continue }
    if ($ln -match '(?i)<tool>:latest|:latest\b.*build\s+context') { continue }
    $ln
  }
  $text = ($kept -join "`n")

  # 3. Ensure the cloud prompt explicitly references the Discovery tool(s) by
  #    name rather than any local image. Appended once, only if not already
  #    present.
  $toolList = ($ToolNames | Sort-Object -Unique) -join ', '
  if ($ToolNames.Count -gt 0 -and $text -notmatch '(?i)Discovery tool\b') {
    $note = @(
      ''
      '## Tool execution (Microsoft Discovery)'
      ''
      "This agent runs in Microsoft Discovery. Its tool(s) ($toolList) are provided as deployed Discovery tools whose container images live in the workspace's Azure Container Registry — invoke them as bound Discovery tools. Do NOT build, pull, or inspect any local Podman/Docker image; there is no local container runtime in the cloud."
    ) -join "`n"
    $text = $text.TrimEnd() + "`n" + $note
  }

  # Collapse any 3+ blank lines left by the scrub down to a single blank line.
  $text = $text -replace "(\r?\n){3,}", "`n`n"
  return $text.Trim()
}
```

#### 4f. Local runtime readiness (conditional)

Run this sub-step **only when `$deployTarget == 'Local'`** and only after the
agent selection in 4e has resolved to at least one agent in `$selected`.

Goal: determine whether Podman and/or Docker are available for local,
lazy image bootstrap done later by generated `.agent.md` companions.

Detection commands:

```pwsh
$hasPodman = $false
$hasDocker = $false
try { & podman --version *> $null; if ($LASTEXITCODE -eq 0) { $hasPodman = $true } } catch {}
try { & docker --version *> $null; if ($LASTEXITCODE -eq 0) { $hasDocker = $true } } catch {}
```

Decision flow:

1. If **both** are installed, ask once which runtime the user prefers for
  local container workflows (`podman` or `docker`). Recommended default:
  `podman`.
2. If only one is installed, set that as `$localContainerRuntimePreference`
  automatically (no prompt).
3. If neither is installed, ask once whether to install Podman automatically.
  - If **yes**, install Podman, then re-check `podman --version`:

    ```pwsh
    winget install --id RedHat.Podman --accept-source-agreements --accept-package-agreements
    ```

    If install succeeds, set `$localContainerRuntimePreference = 'podman'`.
  - If **no**, continue, but print a clear notice that agents with
    container-based tools cannot run until Podman or Docker is installed.

This step must **not** run any image builds; it only selects/installs runtime
prerequisites for future lazy bootstrap.

#### 4d. Discovery workspace + project selection (conditional)

Run this sub-step whenever `$deployToCloud` is true (`$deployTarget` is
`Discovery` or `LocalToDiscovery`). Skip entirely for the `Local` target.

Execute the full login / MCP install / tenant + subscription pick /
workspace pick / project pick / existing-agent listing / confirmation
workflow documented in **Step 7a** (sub-steps 1 through 9). All of Step 7a
runs here in Step 4d - it has been moved up so the destination is locked
in before the user is asked which agents to add.

After 4d completes you have:

- A working proxy at `.vscode/discovery-mcp-proxy.ps1` (sanity-checked via `Invoke-DiscoveryMcp` — not via VS Code's MCP runtime).
- An active `az` CLI session pointed at the correct tenant + subscription.
- `$discoveryTenantId`, `$discoverySubscriptionId`, `$discoveryRg`,
  `$discoveryWorkspace`, and `$discoveryProject` persisted for Steps 7c\u20137e.
- `$existingAgentNames` - the set of agent names already in
  `$discoveryProject`, printed to chat so the user can spot collisions
  **before** picking what to add in 4e.

If the user cancels at the 7a.9 confirmation prompt, stop the workflow
cleanly - do **not** proceed to 4e, do **not** touch ACR or Foundry, and
do **not** copy any agent folders.

When Step 7 runs later, **do not** re-prompt for workspace/project. Skip
straight to Step 7b (Azure MCP probe) and Step 7c (tool ARM pre-flight)
using the values persisted here.

#### 4e. Ask which agents to add

Two-phase prompt flow (`vscode_askQuestions` called up to twice). This is
the agent-selection question batch; deployment target and (when applicable)
workspace/project are already resolved.

**Phase 1 - selection mode** (one question):

```
header: "selection-mode"
question: "How do you want to choose which agents to add?"
options:
  - "All agents"      (recommended)
  - "Specific agents" (user picks individual agents in phase 2)
  - "By group"        (user picks one or more tag groups in phase 2)
```

**Phase 2 - selection value** (skip when `selection-mode == 'All agents'`).
The options list is **scoped to the phase-1 answer**:

| selection-mode    | Phase 2 options                                                                  |
|-------------------|----------------------------------------------------------------------------------|
| `All agents`      | (skip phase 2)                                                                   |
| `Specific agents` | Individual agents only - `[agent] <folder>` entries, sorted alphabetically.   |
| `By group`        | Groups only - `[group] <name> (N)` and `[lightweight] no-container-tools (N)` entries. |

```
header: "selection-value"
question: "Pick one or more <agents | groups>."
multiSelect: true
options: <scoped to the phase-1 mode>
```

**Specific agents mode:** every entry in `$catalog`, label formatted as
`"[agent] <folder>"` with the agent's short description in the option's
`description` field. **Do not include any `[group]` or `[lightweight]`
entries** in this mode.

**By group mode:** every key in `$groups` plus the synthetic
`[lightweight] no-container-tools` entry, label formatted as
`"[group] <name> (N agents)"`. **The option's `description` field MUST
list the member agents.** Do not include individual `[agent]` entries
in this mode.

**Discovery collision hint (only when `$deployToCloud` is true — `$deployTarget` is `Discovery` or `LocalToDiscovery`).**
For each option whose folder name appears in `$existingAgentNames` (from
4d), prepend `[ALREADY IN PROJECT] ` to the option's `description` field
so the user knows re-selecting it will trigger an `UpsertAgent` update in
the chosen project. Do not block the choice - just surface it.

**Local collision hint (only when `$deployTarget == 'Local'`).** For each
option whose folder name appears in `$existingLocalAgents` (the set of
`.github/agents/<name>.agent.md` stems from Step 1), prepend
`[ALREADY ADDED LOCALLY] ` to the option's `description` field so the user
knows re-selecting it will overwrite the existing `.agent.md` companion in
place. Do not block the choice - just surface it. Always derive this hint
from `.github/agents/`, never from `discovery_catalog/` (the latter is
refreshed unconditionally in Step 5 and therefore can't distinguish new vs
already-installed agents).

#### Group member display rule

Every group option presented in phase 2 **must include the names of the
agents in that group** in the option's `description` field. This is how the
user knows what's actually in `drug-discovery`, `cheminformatics`, etc.
without needing to ask back.

Formatting rules for the description:

- Comma-separated, alphabetically sorted folder names.
- Truncate to ~120 characters and append `, \u2026(+N more)` if the full list is
  longer. Example: `"aizynthfinder, autodock, bindingdb, boltztwo, retrochimera, tamgen"`.
- For **Lightweight (no container tools)**, always list the full member set - it's
  small by definition.

Filter the group list shown to the user to **tags with \u2265 2 agents** plus the
synthetic `Lightweight (no container tools)` entry. Singleton tags add noise and the
agent itself is already pickable in `Specific agents` mode.

Sort the group options by member count (descending), so the broadest groups
appear first.

#### Resolve the final selection

Then resolve the final set of folders to add:

- Mode = **All agents** \u2192 `$selected = $catalog.Folder`
- Mode = **Specific agents** \u2192 for each phase-2 answer starting with
  `[agent] `, strip the prefix and look it up in `$catalog.Folder`.
- Mode = **By group** \u2192 for each phase-2 answer starting with `[group] ` or
  `[lightweight] `, strip the prefix and union the folders in `$groups[$name]`
  (or the lightweight set).

Unknown phase-2 entries (typos, freeform): treat as agent folder names and
warn if they don't resolve. If `$selected` is empty after resolution, ask
phase 2 again once; if still empty, stop and report.

Print the resolved selection back to chat before proceeding:

```
Will add 7 agent(s): pubchem, rdkit, online-researcher, ...
```

### Step 5 — Refresh selected agents in `discovery_catalog/`

> **Skip this entire step when `$deployTarget == 'LocalToDiscovery'`**
> (`$sourceMode == 'Local'`). The promote target treats the existing local
> `discovery_catalog/<name>/` folder as the source of truth; overwriting it
> with upstream would discard the local edits being promoted. Jump straight
> to Step 7.

**Always refresh from upstream (Upstream source mode only).** For every folder
in `$selected`, replace `discovery_catalog/<name>/` with the upstream copy from
`agents/<name>/`. This guarantees the local catalog reflects the
latest upstream content (bug fixes, new tools, updated prompts) and that
any change to the agent list is surfaced. **Do not prompt the user before
overwriting** — the `discovery_catalog/` tree is a managed mirror, not
user-authored content.

```pwsh
$srcRoot = Join-Path $work 'agents'
$dstRoot = Join-Path $workspaceRoot 'discovery_catalog'

$createdFolders   = @()   # folder did not exist locally — created fresh
$refreshedFolders = @()   # folder existed locally — overwritten with upstream
$skipped          = @()   # name not in upstream (folder may have been removed)

$selected | ForEach-Object {
    $name = $_
    $src  = Join-Path $srcRoot $name
    $dst  = Join-Path $dstRoot $name
    if (-not (Test-Path $src)) { $skipped += "$name (not in upstream)"; return }
    $existed = Test-Path $dst
    if ($existed) {
        # Always replace in full so renamed/removed files don't linger.
        Remove-Item -Recurse -Force $dst
    }
    Copy-Item -Recurse -Force $src $dst
    if ($existed) { $refreshedFolders += $name } else { $createdFolders += $name }
}
```

**Rules:**

- Always refresh `discovery_catalog/<name>/` from upstream — no overwrite
  prompt. Stale folders silently mask upstream changes.
- Replace each refreshed folder in full (delete then copy) so files removed
  upstream don't linger locally.
- Never touch `discovery_catalog/<name>/` folders that are **not** in
  `$selected` — leave them as-is. Removal of unselected agents is out of
  scope for this step.
- Preserve file casing exactly as upstream (Windows is case-insensitive but the
  repo metadata is case-sensitive on Linux containers).
- Do **not** rename `tools/<Tool>/` — the directory name is referenced by
  `metadata.yaml#associated_tools` and `agent.yaml#discoveryExtensions.tools`.
- The "already added locally" determination for the summary (Step 8) and
  for the Step 4e Local collision hint comes from
  `.github/agents/<name>.agent.md` presence (captured in Step 1 as
  `$existingLocalAgents`), **not** from this folder. Two distinct concepts:
  - `$createdFolders` / `$refreshedFolders` — state of `discovery_catalog/`
  - `$existingLocalAgents`               — state of `.github/agents/`

### Step 6 — Generate Copilot agent companions

For every folder in `$selected` (that successfully copied or was already
present locally), emit a sibling Copilot agent file at
`.github/agents/<name>.agent.md`. This is what makes each Discovery agent
invocable as a Copilot subagent via `runSubagent`.

Do **not** regenerate `.agent.md` files for agents the user did not select in
Step 4 — leaving those files untouched preserves prior selections and avoids
surprising the user.

The Copilot agent file is a markdown file with YAML frontmatter, distinct from
the Discovery `agent.yaml`. Map fields as follows:

| Copilot frontmatter | Source |
|---|---|
| `name` | `discovery_catalog/<name>/agent.yaml#name` (fallback: folder name) |
| `description` | `agent.yaml#description` — first paragraph, collapsed to one line, quoted |
| `argument-hint` | `"Query or input for the <name> agent"` |
| `user-invocable` | `true` |

The **body** of the `.agent.md` file is composed of two parts, in this order:

1. A **container runtime bootstrap preamble** (generated by this skill, see
  template
   below) listing the exact image tags and Dockerfile paths for every tool
   under `discovery_catalog/<name>/tools/`. The preamble instructs the agent
  to verify each image exists locally before invoking the tool, and to build
  it from the matching Dockerfile only if missing. Runtime order is fixed:
  try Podman first, then Docker if Podman is unavailable or fails.
2. The verbatim contents of `agent.yaml#instructions` (the Discovery prompt
   block). Do NOT translate, summarize, or re-wrap it — Discovery agents are
   tuned against that exact text.

Do NOT include a `tools:` frontmatter key. Discovery tool IDs (the `toolId`
placeholders inside `discoveryExtensions.tools`) don't map to Copilot tool
names, and adding the wrong list silently disables tools.

#### Container runtime bootstrap preamble template

For an agent whose folder is `discovery_catalog/<name>/` with tool
subdirectories `tools/<Tool1>/`, `tools/<Tool2>/`, etc., the preamble looks
like this (substitute the agent name and the actual tool rows):

```markdown
# Container image bootstrap (auto-generated by add-agent-from-catalog)

This agent depends on local container images. **Before invoking any
tool, you MUST verify each image exists and build it only if it is missing.**
Do not rebuild images that are already present — builds are expensive.

| Image tag | Build context |
|---|---|
| `<tool1>:latest` | `discovery_catalog/<name>/tools/<Tool1>` |
| `<tool2>:latest` | `discovery_catalog/<name>/tools/<Tool2>` |

Procedure for each image (Podman first, Docker fallback):

1. Try Podman first:
  - `podman image inspect <tag>`; if exit code is `0`, the image exists —
    **skip the build**.
  - If missing, confirm `podman info` succeeds, then run
    `podman build -t <tag> <build-context>`.
2. If Podman is unavailable or fails, fall back to Docker:
  - `docker image inspect <tag>`; if exit code is `0`, the image exists —
    **skip the build**.
  - If missing, confirm `docker info` succeeds, then run
    `docker build -t <tag> <build-context>`.
3. If neither runtime is available, stop and report that Podman or Docker
  must be installed before container-based tools can run.
4. Never `podman push` / `docker push` and never touch any registry — this bootstrap is
   strictly local.

Do this lazily — only when a tool is actually about to be invoked, not on
every turn. After a successful build, the image will satisfy the
inspect check on subsequent runs.
```

When an agent has **no** `tools/*/Dockerfile` (rare — e.g. pure LLM agents like
`bookshelf-researcher`, `online-researcher`), omit the preamble entirely.

#### Generation script

Use the `powershell-yaml` module if available, otherwise parse with a
regex-lite reader that extracts only the three fields we need (`name`,
`description`, `instructions`). Always overwrite existing `.agent.md` files —
they are derived artifacts, not user-edited.

**Mandatory hardening from observed local runs:**

- Materialize the generation logic into a temp `.ps1` file and run it with
  `pwsh -NoProfile -File`; do not paste this multi-line script directly into
  the shared terminal.
- For `.github/agents/*.agent.md` collision detection, strip the full
  `.agent.md` suffix. Never use `.BaseName`, because `pubchem.agent.md`
  becomes `pubchem.agent`.
- Treat YAML block-scalar markers (`|`, `|-`, `>`, `>-`) as "no inline value"
  and then read the indented block. Otherwise generated frontmatter can become
  `description: "|"` instead of the real description.
- Write generated `.agent.md` files with a `FileStream` opened with
  `FileShare.ReadWrite`. VS Code and the extension host may briefly read these
  files during generation; plain `Set-Content` can fail with "file is being
  used by another process". A rerun is safe, but the shared writer avoids most
  transient locks.

```pwsh
$agentsDir = Join-Path $workspaceRoot '.github/agents'
New-Item -ItemType Directory -Force -Path $agentsDir | Out-Null

function Get-SimpleYamlValue([string[]]$Lines, [string]$Key) {
  foreach ($line in $Lines) {
    if ($line -match ("^" + [regex]::Escape($Key) + ":\s*(.+)$")) {
      $value = $matches[1].Trim().Trim('"').Trim("'")
      if ($value -match '^[>|][-+]?$') { return '' }
      return $value
    }
  }
  return ''
}

function Get-YamlBlock([string[]]$Lines, [string]$Key) {
  $start = -1
  for ($i = 0; $i -lt $Lines.Count; $i++) {
    if ($Lines[$i] -match ("^" + [regex]::Escape($Key) + ":\s*[>|][-+]?\s*$")) {
      $start = $i + 1
      break
    }
  }
  if ($start -lt 0) { return '' }

  $end = $Lines.Count - 1
  for ($i = $start; $i -lt $Lines.Count; $i++) {
    if ($Lines[$i] -match '^[A-Za-z0-9_-]+:\s*') {
      $end = $i - 1
      break
    }
  }
  if ($end -lt $start) { return '' }

  $block = @($Lines[$start..$end])
  $nonBlank = $block | Where-Object { $_ -match '\S' }
  $minIndent = 0
  if ($nonBlank.Count -gt 0) {
    $minIndent = ($nonBlank | ForEach-Object {
      if ($_ -match '^(\s*)') { $matches[1].Length }
    } | Measure-Object -Minimum).Minimum
  }
  $out = $block | ForEach-Object {
    if ($_.Length -ge $minIndent) { $_.Substring($minIndent) } else { $_ }
  }
  return (($out -join "`n").TrimEnd())
}

function Escape-FrontmatterDoubleQuoted([string]$Value) {
  if ($null -eq $Value) { return '' }
  return (($Value.Replace('\', '\\').Replace('"', '\"')) -replace "`r?`n", ' ')
}

function Write-GeneratedText([string]$Path, [string]$Text) {
  $encoding = [System.Text.UTF8Encoding]::new($false)
  $stream = [System.IO.File]::Open(
    $Path,
    [System.IO.FileMode]::Create,
    [System.IO.FileAccess]::Write,
    [System.IO.FileShare]::ReadWrite)
  try {
    $writer = [System.IO.StreamWriter]::new($stream, $encoding)
    try { $writer.Write($Text) } finally { $writer.Dispose() }
  } finally {
    $stream.Dispose()
  }
}

$existingLocalAgents = @{}
Get-ChildItem $agentsDir -Filter '*.agent.md' -File -ErrorAction SilentlyContinue | ForEach-Object {
  $stem = $_.Name -replace '\.agent\.md$', ''
  $existingLocalAgents[$stem] = $true
}

$generated = @(); $skipped = @()
$selected | ForEach-Object {
    $folder    = $_
    $agentDir  = Join-Path $workspaceRoot "discovery_catalog/$folder"
    if (-not (Test-Path $agentDir)) { $skipped += "$folder (folder missing)"; return }
    $agentYaml = Join-Path $agentDir 'agent.yaml'
    if (-not (Test-Path $agentYaml)) { $skipped += "$folder (no agent.yaml)"; return }

    $lines = @(Get-Content $agentYaml)

    $name = Get-SimpleYamlValue $lines 'name'
    if ([string]::IsNullOrWhiteSpace($name)) { $name = $folder }

    $desc = Get-SimpleYamlValue $lines 'description'
    if ([string]::IsNullOrWhiteSpace($desc)) {
      $descBlock = Get-YamlBlock $lines 'description'
      $desc = ($descBlock -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 1).Trim()
    }
    if ([string]::IsNullOrWhiteSpace($desc)) { $desc = "Discovery agent: $folder" }
    $descEsc = Escape-FrontmatterDoubleQuoted $desc

    $instructions = Get-YamlBlock $lines 'instructions'
    if ([string]::IsNullOrWhiteSpace($instructions)) {
      $instructions = '(No instructions defined in agent.yaml.)'
      $skipped += "$folder (empty instructions)"
    }

    # Enumerate tool images for the container-runtime bootstrap preamble.
    $toolRows = @()
    $toolsRoot = Join-Path $agentDir 'tools'
    if (Test-Path $toolsRoot) {
        Get-ChildItem $toolsRoot -Directory | ForEach-Object {
            if (Test-Path (Join-Path $_.FullName 'Dockerfile')) {
                $tag = ($_.Name).ToLower() + ':latest'
                $ctx = "discovery_catalog/$folder/tools/$($_.Name)"
                $toolRows += "| ``$tag`` | ``$ctx`` |"
            }
        }
    }

    $preamble = ''
    if ($toolRows.Count -gt 0) {
        $preamble = @(
            '# Container image bootstrap (auto-generated by add-agent-from-catalog)'
            ''
            'This agent depends on local container images. **Before invoking any tool, you MUST verify each image exists and build it only if it is missing.** Do not rebuild images that are already present.'
            ''
            '| Image tag | Build context |'
            '|---|---|'
        ) + $toolRows + @(
            ''
            'For each image (Podman first, Docker fallback):'
            ''
            '1. Try Podman first: run `podman image inspect <tag>`. If exit code is `0`, the image exists — **skip the build**. If missing, confirm `podman info` succeeds, then run `podman build -t <tag> <build-context>`.'
            '2. If Podman is unavailable or fails, fall back to Docker: run `docker image inspect <tag>`. If exit code is `0`, the image exists — **skip the build**. If missing, confirm `docker info` succeeds, then run `docker build -t <tag> <build-context>`.'
            '3. If neither runtime is available, stop and report that Podman or Docker must be installed before container-based tools can run.'
            '4. Never `podman push` / `docker push` and never touch a registry — bootstrap is strictly local.'
            ''
            'Do this lazily — only when a tool is actually about to be invoked.'
            ''
            '---'
            ''
        ) -join "`n"
    }

    $frontmatter = @(
        '---'
        "name: $name"
        "description: `"$descEsc`""
        "argument-hint: `"Query or input for the $name agent`""
        'user-invocable: true'
        '---'
        ''
    ) -join "`n"

    $out = Join-Path $agentsDir "$folder.agent.md"
    Write-GeneratedText -Path $out -Text ($frontmatter + $preamble + $instructions + "`n")
    $generated += $folder
}
```

Rules:

- Use the **folder name** as the `.agent.md` filename (e.g.
  `discovery_catalog/pubchem/` → `.github/agents/pubchem.agent.md`). This
  guarantees no collisions even if two `agent.yaml` files share a `name:` field.
- Always **overwrite** existing `.agent.md` files. They are derived, not
  hand-authored. Do NOT prompt the user about overwrites in `.github/agents/`.
- Preserve hand-authored Copilot agents (`batteries-included.agent.md`,
  `bookshelf-researcher.agent.md`, `project-setup-orchestrator.agent.md`) by
  only writing files whose stem matches a `discovery_catalog/<name>/` folder.
- If `agent.yaml#instructions` is missing or empty, still emit the frontmatter
  with a body of `(No instructions defined in agent.yaml.)` and record the
  agent in the summary's `skipped`/`degraded` list.
- Omit the container-runtime bootstrap preamble entirely for agents that have no
  `tools/*/Dockerfile` upstream.
- Do not embed any local `podman build` / `docker build` calls in this skill
  itself — the skill must never invoke local image builds.

### Step 7 — Deploy to Microsoft Discovery + Azure (conditional)

Run this step when `$deployToCloud` is true — i.e. `$deployTarget` from
Step 4c is either `Discovery` (upstream-sourced) or `LocalToDiscovery`
(promoted from the local app). For each folder in `$selected`, this step
pushes the agent's tool container image(s) to Azure Container Registry and
registers the agent in the Microsoft Discovery agent registry as a hosted
prompt agent.

**Source difference for `LocalToDiscovery`:** the local workspace is the
source — nothing is re-fetched from upstream. Each selected agent falls into
one of two buckets (classified in Step 4c.LTD via
`$agentHasCatalogFolder`):

- **Tool-bearing** (`discovery_catalog/<name>/` exists) — the tool subtree
  files (`metadata.yaml`, `tools/<Tool>/Dockerfile`, `tool.yaml`) and the
  `name` / `description` fields come from that local folder. The
  **`instructions`** come from the `.github/agents/<name>.agent.md`
  companion (via `Get-AgentMdInstructions`), **not** from `agent.yaml`
  (see Step 7e.1). Tool images are pushed from the local build context /
  locally-built image (see Step 7d.LTD). Runs the full 7c → 7d → 7e path.
- **Toolless** (no `discovery_catalog/<name>/` folder) — the agent has **no
  container tool**. Skip 7c and 7d entirely (nothing to pre-flight, build,
  or bind). Source `name` / `description` / `instructions` from the
  `.github/agents/<name>.agent.md` companion (see the
  `Get-AgentMdInstructions` helper in Step 4c.LTD) and go straight to 7e
  with an empty `toolIds`.

Everything else — workspace/project pick (7a), MCP probe (7b),
`UpsertAgent` + `GetAgent` poll (7e) — is identical for both buckets.

**Workspace + project were already chosen in Step 4d.** Do **not** re-prompt
for tenant, subscription, workspace, or project here. Reuse
`$discoveryTenantId`, `$discoverySubscriptionId`, `$discoveryRg`,
`$discoveryWorkspace`, `$discoveryProject`, and `$existingAgentNames`
persisted by 4d. Step 7a below documents the workspace/project picker
**only** so 4d has something concrete to invoke; in normal flow, 7a never
runs from inside Step 7 — it has already run as part of 4d.

**Prefer MCP servers over raw CLI commands.** Use the Discovery MCP and Azure
MCP whenever they are available; only fall back to terminal commands when the
required MCP capability is not present.

#### 7a. Discovery login, workspace + project selection, existing-agent listing

> **Where this runs.** In the normal flow, 7a is invoked **from Step 4d**
> (before the agent picker), not from inside Step 7. The sub-section
> remains under Step 7 because it is part of the Discovery deploy machinery;
> Step 4d explicitly delegates to it. If you find yourself entering Step 7
> without `$discoveryWorkspace` / `$discoveryProject` set, you skipped 4d —
> go back and run it before continuing.

Before asking for Azure resource names, the user must be signed in to
Microsoft Discovery and must pick the Discovery **workspace** and **project**
the new agents will be deployed into. Always show the currently-registered
agents in the chosen project **before** Step 7c pre-flights the tool ARMs
and (if needed) Step 7c.2 prompts for ACR/RG, so the user can spot
duplicates and abort early.

1. **Install the proxy (single extraction, no probe).** The Discovery MCP
  server is the Microsoft-hosted remote streamable-HTTP endpoint at
  `https://mcp.discovery.azure.com/mcp`. The skill embeds the PowerShell
  stdio proxy and invocation helper at the end of this `SKILL.md`; the
  bootstrap below extracts them into `.vscode/` so PowerShell and VS Code
  can execute normal `.ps1` files. **Always materialize** the scripts into
  `.vscode/` at the start of Step 4d — do NOT probe for it first, do NOT depend on VS Code's MCP
   runtime ever surfacing `mcp_microsoft-dis_*` deferred tools in this
   session:

   ```pwsh
   $skillDir = '<absolute path to add-agent-from catalog folder>'
   New-Item -ItemType Directory -Force -Path "$workspaceRoot\.vscode" | Out-Null
  $skillPath = Join-Path $skillDir 'SKILL.md'
  $skillText = Get-Content $skillPath -Raw
  function Write-EmbeddedSkillScript([string]$BlockId, [string]$Destination) {
       $begin = "<!-- BEGIN:$BlockId -->"
       $end = "<!-- END:$BlockId -->"
       $start = $skillText.IndexOf($begin)
       if ($start -lt 0) { throw "Embedded script block '$BlockId' not found in $skillPath" }
       $contentStart = $start + $begin.Length
       $stop = $skillText.IndexOf($end, $contentStart)
       if ($stop -lt 0) { throw "Embedded script block '$BlockId' has no end marker in $skillPath" }
       $block = $skillText.Substring($contentStart, $stop - $contentStart).Trim()
       $lines = @($block -split "`r?`n")
       if ($lines.Count -lt 3 -or $lines[0] -notmatch '^```powershell\s*$' -or $lines[-1] -notmatch '^```\s*$') {
           throw "Embedded script block '$BlockId' must be wrapped in a powershell fenced code block."
       }
       $content = (($lines[1..($lines.Count - 2)]) -join "`r`n") + "`r`n"
       Set-Content -Path $Destination -Value $content -Encoding UTF8
   }
   Write-EmbeddedSkillScript 'embedded-discovery-mcp-proxy.ps1' "$workspaceRoot\.vscode\discovery-mcp-proxy.ps1"
   Write-EmbeddedSkillScript 'embedded-Invoke-DiscoveryMcp.ps1' "$workspaceRoot\.vscode\Invoke-DiscoveryMcp.ps1"
   ```

   That is the entire MCP install. From here on, **every** MCP call goes
  through `Invoke-DiscoveryMcp` (extracted helper) → proxy → HTTPS. See
   the "Scripted MCP invocation" section near the top of this skill for
   the canonical call pattern.

   The legacy `agents action=registry.list` probe, the mcp.json HTTP
   server entry, the `workbench.action.mcp.restart` ritual, and the
   `workbench.action.mcp.listServers` fallback are **all optional** and
   only benefit the user's future interactive VS Code sessions. They do
   nothing for this skill's run — do not waste turns on them. If you
   still want to write `.vscode/mcp.json` for the user's convenience,
   do it once with the merge-safe script in 7a.2 below and **do not**
   block on the restart or any tool surfacing.

   Sanity-check the proxy is reachable in one quick call:

   ```pwsh
  . "$workspaceRoot\.vscode\Invoke-DiscoveryMcp.ps1"
   $r = Invoke-DiscoveryMcp -ProxyPath "$workspaceRoot\.vscode\discovery-mcp-proxy.ps1" -Calls @(@{ name='Ping'; args=@{} })
   if (-not $r['2']) { throw 'Proxy not responding — check az login and PowerShell 7+.' }
   ```

2. **(Optional, courtesy)** Register the proxy in `.vscode/mcp.json` so
   it shows up in the user's MCP server list for future interactive
   sessions. This is a write-once, fire-and-forget step — the rest of
   the skill does NOT depend on VS Code loading those tools.

      **`.vscode/discovery-mcp-proxy.ps1`** is the canonical proxy
      implementation generated from this `SKILL.md`. The embedded block
      below is authoritative — extract it verbatim into new workspaces; do
      not reimplement it inline. Requirements: PowerShell 7+ (uses
      `Invoke-WebRequest -SkipHttpErrorCheck`) and `az` CLI on PATH with
      an active session.

      **`.vscode/mcp.json`** — register the proxy as a stdio server:
      ```json
      {
        "servers": {
          "microsoft-discovery": {
            "type": "stdio",
            "command": "pwsh",
            "args": [
              "-NoProfile",
              "-File",
              "${workspaceFolder}/.vscode/discovery-mcp-proxy.ps1"
            ]
          }
        }
      }
      ```

      **Idempotent merge script** — read existing `.vscode/mcp.json` (if
      any), drop any legacy `discovery-token` promptString input and any
      legacy `type: "http"` microsoft-discovery server from earlier
      versions of this skill, then insert the canonical stdio entry.
      Preserve every other server and input untouched.

      ```pwsh
      $mcpPath = Join-Path $workspaceRoot '.vscode/mcp.json'
      $mcpDir  = Split-Path $mcpPath -Parent
      if (-not (Test-Path $mcpDir)) { New-Item -ItemType Directory -Force -Path $mcpDir | Out-Null }

      if (Test-Path $mcpPath) {
          $cfg = Get-Content $mcpPath -Raw | ConvertFrom-Json -Depth 10
      } else {
          $cfg = [pscustomobject]@{ servers = [pscustomobject]@{} }
      }
      if (-not $cfg.PSObject.Properties['servers']) {
          $cfg | Add-Member -NotePropertyName servers -NotePropertyValue ([pscustomobject]@{})
      }

      # Drop the legacy promptString-based discovery-token input.
      if ($cfg.PSObject.Properties['inputs']) {
          $remaining = @($cfg.inputs | Where-Object { $_.id -ne 'discovery-token' })
          if ($remaining.Count -eq 0) {
              $cfg.PSObject.Properties.Remove('inputs')
          } else {
              $cfg.inputs = $remaining
          }
      }

      # Canonical stdio-proxy server entry.
      $serverEntry = [pscustomobject]@{
          type    = 'stdio'
          command = 'pwsh'
          args    = @('-NoProfile', '-File', '${workspaceFolder}/.vscode/discovery-mcp-proxy.ps1')
      }
      if ($cfg.servers.PSObject.Properties['microsoft-discovery']) {
          $cfg.servers.'microsoft-discovery' = $serverEntry
      } else {
          $cfg.servers | Add-Member -NotePropertyName 'microsoft-discovery' -NotePropertyValue $serverEntry
      }

      $cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $mcpPath -Encoding UTF8
      ```

      Guard-rails:
      - Never blow away the file — always merge. Other servers (GitHub
        MCP, Azure MCP, etc.) under `servers` and other entries under
        `inputs` must remain byte-for-byte.
      - **Always overwrite** any pre-existing `microsoft-discovery`
        entry — including legacy `type: "http"` configs with the
        `promptString` bearer header. The stdio proxy is the only
        supported config for this skill.
      - Do **not** write tokens, tenant IDs, or subscription IDs into
        `mcp.json`. The proxy reads the active `az` session at runtime,
        which is configured by Step 7a.2.5 below.

  2.6. **(Optional) Restart the VS Code MCP server** - only useful for
       the user's future interactive sessions; the skill itself does
       NOT use the surfaced `mcp_microsoft-dis_*` tools. Skipping this
       step is **fine** - the proxy + `Invoke-DiscoveryMcp` work
       without any restart.

       If you do want to be polite to the user:
       1. Try `run_vscode_command commandId='workbench.action.mcp.restart'`
          (no window reload). If the command id isn't found, stop - do
          NOT escalate to a window reload mid-run.
       2. **Do not** smoke-test by waiting for `mcp_microsoft-dis_*`
          tools to appear via `tool_search`. They frequently do not
          appear in the same session. Smoke-test via the proxy instead:

       ```pwsh
         . "$workspaceRoot\.vscode\Invoke-DiscoveryMcp.ps1"
       $r = Invoke-DiscoveryMcp -ProxyPath "$workspaceRoot\.vscode\discovery-mcp-proxy.ps1" -Calls @(
           @{ name='ListWorkspaces'; args=@{ subscriptionId=$discoverySubscriptionId } }
       )
       (Get-DiscoveryMcpText -Response $r['2'] -AsJson).value.Count   # > 0 means healthy
       ```

       Common failure \u2192 fix:

       | Symptom from proxy                              | Cause                                                              | Fix                                                                                              |
       |-------------------------------------------------|--------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
       | `pwsh: command not found` from terminal        | PowerShell 7+ is not on PATH                                       | Install with `winget install Microsoft.PowerShell` - Windows PowerShell 5.1 is too old           |
       | `az: command not found` on proxy stderr         | Azure CLI is not on PATH for the proxy's shell                     | Install Azure CLI and reopen the terminal so the new PATH is inherited                            |
       | `401 InvalidAuthenticationTokenTenant`          | `az` is signed into the wrong tenant for the chosen subscription   | Re-run Step 7a.2.5 (`az login --tenant <id>`); the proxy auto-refreshes on the next request      |
       | `AADSTS500011` (resource principal not found)   | Tenant has never consented to the Discovery first-party app        | Admin consent required - surface the error and stop; the skill cannot fix this                  |
       | `mcp_microsoft-dis_*` tools never appear        | VS Code MCP runtime hasn't surfaced them (common, often permanent) | **Ignore** - use the proxy via `Invoke-DiscoveryMcp` instead. Do NOT poll `tool_search` for them. |
       | Proxy exits with non-zero on launch             | `az account get-access-token` failed at startup                     | Re-run Step 7a.2.5 to fix the `az` session, then try again                                       |

  2.5. **Prompt the user for tenant + subscription and run `az` on their
       behalf.** Do this **before** starting (or restarting) the Discovery
       MCP server so the bearer-token input resolves cleanly.

       **Always prompt.** Even when `az account show` already returns a
       valid session and `/memories/repo/` has a previously-used tenant
       and subscription, you MUST still ask the user. Saved values are
       used **only** to mark the matching option as `recommended: true`
       in the picker — never to auto-select and skip the prompt. The
       user opted into the Discovery + Azure path; that opt-in does not
       grant permission to silently reuse a prior destination.

       Workflow:

       a. Run `az account list --query "[].{name:name, id:id, tenantId:tenantId, isDefault:isDefault}" -o json`
          to enumerate every subscription the user has at least Reader on.
          Group the results by `tenantId` so the picker lists each tenant
          alongside its subscriptions.
       b. Ask the user **once** with `vscode_askQuestions` (two questions
          in a single call):
          - **Question 1 — `discovery-tenant`** (single-select, required):
            options are the distinct `tenantId` values from (a). Label
            each with a short alias derived from the most common
            subscription suffix (e.g. `"corp (72f988bf-…)"`) and put the
            full GUID + member-subscription count in the `description`
            field. If `/memories/repo/` has a previously-used tenant,
            mark that option as `recommended: true` so it appears as the
            default — but the prompt must still be shown.
          - **Question 2 — `discovery-subscription`** (single-select,
            required, freeform allowed): options are the subscriptions in
            the tenant chosen in Q1. Label `"<name> (<sub-id-prefix>…)"`,
            full GUID in `description`. Mark the previously-used
            subscription (if any in `/memories/repo/`) as
            `recommended: true`; otherwise mark the `isDefault: true`
            subscription that way.

          The picker is a **single `vscode_askQuestions` call with two
          questions** — do **not** call it twice. Because Q2's option list
          depends on Q1's answer, build Q2 with **all** subscriptions
          across all tenants and let the user filter — or, if you want a
          two-phase flow, ask Q1 first, then make a second call for Q2
          scoped to the chosen tenant. Either is acceptable; the two-phase
          flow keeps the option list short.

       c. Persist the chosen values as `$discoveryTenantId` and
          `$discoverySubscriptionId` and write them to `/memories/repo/`
          so future runs can pre-select (not auto-select) them as the
          recommended option.
       d. Run, in this order, in a **foreground** terminal so the user can
          complete device-flow auth if prompted:
          ```pwsh
          az login --tenant $discoveryTenantId
          az account set --subscription $discoverySubscriptionId
          ```
          If `az account show` already reports the chosen tenant and
          subscription, you may skip the `az login` call and only run
          `az account set` — the user is already signed in to the right
          identity, so re-auth would be pointless friction. The
          **prompt** in step (b) is still mandatory; only the underlying
          `az login` invocation is conditional on the existing session.
          If `az login` does run and opens the browser, wait for it to
          finish (the terminal will return). If it falls back to device
          code, the user types it directly into the browser — never
          relay codes through `vscode_askQuestions`.
       e. Verify with `az account show --query "{sub:id, tenant:tenantId}"
          -o json`; both values must match the user's choices. If not,
          stop and report — do not proceed to MCP restart with a
          mismatched session.
       f. Validate the resource token actually mints:
          ```pwsh
          az account get-access-token --resource https://discovery.azure.com --query "{tenant:tenant, expiresOn:expiresOn}" -o json
          ```
          A success here means the MCP's `command`-input will resolve. A
          failure (e.g. `AADSTS500011` "resource principal not found")
          means the tenant has never consented to the Discovery first-party
          app — surface that exact error and stop; admin consent is
          required and cannot be granted from this skill.

       Never ask the user for tokens, passwords, or device codes through
       `vscode_askQuestions` — answers to that tool go through the model.
       Tenant and subscription **IDs** are not secrets and are fine to
       collect via the picker.
   3. **None of the above worked.** Stop the workflow and report exactly
      which probe failed (network error, sign-in declined, etc.) plus the
      manual install instructions:
      *Open Command Palette → "MCP: Add Server" → "HTTP" → URL
      `https://mcp.discovery.azure.com/mcp` → name `microsoft-discovery`*.
      **Never** spoof a session or fabricate registry data.

   Do **not** prompt for credentials, tokens, or secrets via
   `vscode_askQuestions` at any point in the install — the MCP server's
   own auth handshake (browser / Entra) is the only safe channel.

2. **Probe authentication via the proxy** (NOT via VS Code's MCP
   runtime). With `az` already pointed at the correct
   tenant/subscription (Step 7a.2.5), call any cheap MCP tool through
   `Invoke-DiscoveryMcp`:

   ```pwsh
     . "$workspaceRoot\.vscode\Invoke-DiscoveryMcp.ps1"
   $r = Invoke-DiscoveryMcp -ProxyPath "$workspaceRoot\.vscode\discovery-mcp-proxy.ps1" -Calls @(
       @{ name='ListWorkspaces'; args=@{ subscriptionId=$discoverySubscriptionId } }
   )
   ```

   - A JSON payload with `value[]` confirms the session is good.
   - On `401 InvalidAuthenticationTokenTenant`, the `az` CLI is signed
     into the wrong tenant. Re-run Step 7a.2.5 to pick the correct
     tenant/subscription. The proxy refreshes its token on the next
     call automatically — no server restart needed.
   - On `AADSTS500011` (resource principal not found), the tenant has
     never consented to the Discovery first-party app. Surface the
     error and stop — admin consent required.

3. **Run interactive sign-in if needed.** If the probe in (2) fails
   with `401`, re-run Step 7a.2.5 (re-prompts for tenant + subscription
   and re-runs `az login --tenant <id>`). Do **not** prompt for
   credentials, tokens, or device codes via `vscode_askQuestions` — the
   user types them directly into the browser or terminal that `az login`
   opens.

4. **List workspaces** the signed-in user can access in
   `$discoverySubscriptionId`:
   - **Always via the proxy** — call `ListWorkspaces` through
     `Invoke-DiscoveryMcp` (see step 2 above for the exact pattern).
     The response is `{ "value": [ {name, id, location, …}, … ] }`.
     Do **not** wait for VS Code to surface `mcp_microsoft-dis_ListWorkspaces`
     as a deferred tool — it often never appears.
     not already loaded.
   - Fallback: `az resource list --subscription $discoverySubscriptionId
     --resource-type Microsoft.Discovery/workspaces --output json`.
   - Filter out workspaces the user lacks `Contributor` (or higher) role on
     — they can't deploy into those. If the filter would remove every entry,
     show the full list with a warning instead.

5. **ALWAYS ask the user to pick a workspace** with `vscode_askQuestions`
   (single-select, required). The option label is the workspace display
   name; the `description` field includes the workspace ID and region so the
   user can disambiguate similarly-named workspaces. If
   `/memories/repo/` has a previously-used workspace **in the chosen
   subscription**, mark that option as `recommended: true` — but the
   prompt is mandatory on every Discovery run. Never auto-select a
   workspace from saved memory, environment variables, or a single-entry
   list; always surface the picker so the user explicitly confirms the
   destination.

6. **List projects** inside the chosen workspace:
   - **Always via the proxy**: call `ListProjects` through
     `Invoke-DiscoveryMcp` with
     `subscriptionId=$discoverySubscriptionId`,
     `resourceGroupName=<rg-of-chosen-workspace>`, and
     `workspaceName=<chosen-workspace-name>`. Do not depend on
     `mcp_microsoft-dis_ListProjects` being surfaced as a deferred tool.
   - Fallback: `az rest --method get --uri
     "https://management.azure.com/subscriptions/$discoverySubscriptionId/resourceGroups/<rg>/providers/Microsoft.Discovery/workspaces/<ws>/projects?api-version=2026-06-01"`.
   - Show project display name + ID + the underlying Foundry project URI in
     the option `description`.

7. **ALWAYS ask the user to pick a project** with `vscode_askQuestions`
   (single-select, required). Persist the result as `$discoveryWorkspace`
   and `$discoveryProject` (full ID, not just display name). Same rule
   as step 5: a previously-used project may be marked
   `recommended: true`, but the prompt is mandatory on every Discovery
   run — never auto-select.

8. **List existing agents in the chosen project** and show them to the user
   verbatim before proceeding:
   - Prefer `agents action=list` filtered to the registry that corresponds
     to `$discoveryProject`. Call `agents action=registry.list` first to
     find the matching registry name.
   - Fallback: `discovery agents list --project <project-id>`.
   - Print a table with: agent name, version (or last-updated timestamp),
     tool count, and whether the name collides with any folder in
     `$selected`. Highlight collisions clearly — they will trigger the
     "update vs create" question in Step 7e.

9. **Confirm before continuing.** Ask one more `vscode_askQuestions`:
   *"Proceed to deploy N agents to project `<project-name>`?"* with options
   `Yes` (default) and `Cancel`. On `Cancel`, stop the workflow cleanly — do
   not touch ACR or Foundry.

Persist `$discoveryWorkspace`, `$discoveryProject`, `$discoverySubscriptionId`,
and `$discoveryRg` for use in Step 7c (tool pre-flight against the
workspace's RG) and Step 7e (agent provisioning via `UpsertAgent`).

#### 7b. Probe MCP availability for Azure

Discovery MCP — always available in a Discovery workspace as the `agents` and
`tools` tools:

| Capability | MCP call |
|---|---|
| List registered agents | `agents` with `action: list` |
| Create / update an agent | `agents` with `action: create` (or `update`) |
| List available tool grants | `agents` with `action: tools.list` |
| Assign tools to an agent | `agents` with `action: assign-tools` |
| List / refresh registries | `agents` with `action: registry.list` / `registry.refresh` |

Azure MCP — **probe first**, do not assume it is installed. Call:

```
tools action=search query='azure'
tools action=search query='azure container registry'
tools action=search query='azure subscription'
```

If a callable Azure plugin is returned (`status: 'callable'`), use its tools
(e.g. ACR build/push, subscription select, role assignment) instead of `az`
CLI. If only `metadata_only` plugins are returned, ask the user **once**
whether to install one of them; otherwise fall back to the `az` and `docker`
CLIs (documented inline in Step 7d).

Do **not** silently install Azure MCP plugins — installation makes them
available globally and the user should opt in.

#### 7c. Pre-flight: detect pre-existing tool ARM resources

**Skip this entire step for toolless agents** (`LocalToDiscovery` agents
with no `discovery_catalog/<name>/` folder, or any agent that declares no
`tools/<Tool>/` subdirectories). Set `$skipImageBuild = $true`, leave
`$preExistingToolIds` / `$builtToolIds` empty, and jump straight to Step 7e.
There is nothing to pre-flight, build, or bind.

**Many catalog agents are already partially deployed in shared Discovery
workspaces.** Before asking the user for ACR/RG/region (Step 7c.2) and
before building any images (Step 7d.1), call
`GetDiscoveryTool` (called via `Invoke-DiscoveryMcp`) once per tool declared under
`discovery_catalog/<name>/tools/<Tool>/` against the **workspace's resource
group** (`$discoveryRg` from Step 7a — *not* the deployment ACR's RG).

```
for $tool in (Get-ChildItem discovery_catalog/<name>/tools/ -Directory):
    GetDiscoveryTool subscriptionId=$discoverySubscriptionId
                     resourceGroupName=$discoveryRg
                     toolName=$tool.Name
```

Outcomes:

| Result                                        | Interpretation                                                   | Action                                                                                                                |
|-----------------------------------------------|------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| `200` with `provisioningState=Succeeded`      | Tool already registered as ARM resource; image already pushed     | Capture the `.id` (ARM resource ID) and `.properties.definitionContent.infra[].image.acr`. **Skip build & push for this tool.** |
| `200` with `provisioningState=Failed`         | Stale half-deployed resource                                      | Surface to user; ask whether to delete + recreate (default: leave alone, abort agent)                                |
| `404` not found                               | Tool not registered yet                                           | Build + push + register (Step 7d). Need ACR + RG (Step 7c.2)                                                          |
| `403` / token expired                         | MCP auth issue                                                    | Re-run Step 7a.2.6 mint/restart                                                                                       |

Set `$skipImageBuild = $true` only when **every** tool the agent declares
returns `Succeeded`. Otherwise `$skipImageBuild = $false` and you must
collect ACR config in Step 7c.2.

**Why this matters.** The Microsoft Discovery catalog ships agents whose
tool images are already published to a shared registry like `mdqacr`. In
that case there is nothing to build — the entire Docker/ACR/RBAC pipeline
is a no-op. Detecting this up front avoids prompting the user for an ACR
they don't own and avoids ~5–15 min of unnecessary build time.

**A previously-deployed tool ARM may have been deleted since your last run**
(shared dev workspaces get cleaned up), so a `404` here does **not** mean the
image is gone. Before falling into the full ACR-build prompt flow (Step 7c.2 /
7d), check whether the image already exists in the expected ACR
(`az acr repository show-tags --name <acr> --repository <tool>`). If the image
is present, **skip the build** and go straight to re-registering the tool ARM
from the local `tool.yaml` (Step 7d.4: PUT `definitionContent` as an object,
`language: python3`), poll `GetDiscoveryTool` to `Succeeded`, ensure AcrPull
(idempotent), then bind it in Step 7e. Only build when the image is genuinely
absent from the ACR.

Also list existing agents in the target project so the user can see whether
the agent name is already taken — this is the data behind the
"update vs create" question in Step 7e:

```
ListAgents subscriptionId=$discoverySubscriptionId
           resourceGroupName=$discoveryRg
           workspaceName=$discoveryWorkspace
           projectName=$discoveryProject
```

Persist `$preExistingToolIds` (map of `toolName → ARM resource ID`),
`$skipImageBuild`, and `$existingAgentNames` for downstream steps.

#### 7c.2. Collect Azure deployment configuration (only if $skipImageBuild == $false)

Skip this entire sub-step when `$skipImageBuild == $true` — there's no
image to push, no ACR to choose, no RG to provision. Jump straight to Step
7d.

Otherwise ask the user **once** (single `vscode_askQuestions` call with
multiple questions) for the Azure targets. Pre-fill defaults from the
environment when possible (`az account show`, `$env:AZURE_SUBSCRIPTION_ID`,
prior session memory under `/memories/repo/`).

The **Foundry project name** is already known from Step 7a
(`$discoveryProject`); use it as the default for the Foundry project field
and allow the user to override it only if they explicitly need a different
target.

Required values:

- **Azure subscription** (id or name) — default `$discoverySubscriptionId`
- **Resource group** (existing or to-create) — default `$discoveryRg`
- **Azure Container Registry** name (the image registry — must be reachable
  from the Foundry project that will host the agent). Pre-populate by
  calling `az acr list --subscription <sub> -o json` and surfacing
  registries in the same region as `$discoveryWorkspace.location` first.
- **Foundry project** name (defaults to `$discoveryProject`)
- **Region** (only if the resource group or ACR needs to be created) —
  default `$discoveryWorkspace.location`

Never prompt for secrets via `vscode_askQuestions` (it ships answers through
the model). If a token or key is needed, instruct the user to type it
directly into the terminal.

#### 7d. Build + push tool images (only if $skipImageBuild == $false)

If every tool in the agent already exists as an ARM resource (Step 7c set
`$skipImageBuild = $true`), skip this entire step and jump to Step 7e.

**7d.LTD — pushing a locally-built image (`$deployTarget == 'LocalToDiscovery'`).**
When promoting from the local app, the tool image may already be built locally
(via Podman/Docker from a prior local invocation). Two acceptable paths, in
order of preference:

1. **Cloud build from the local Dockerfile (preferred, reproducible).** Run
   `az acr build` exactly as in the numbered steps below, using the local
   `discovery_catalog/<name>/tools/<Tool>/` build context. This ignores any
   locally-built image and rebuilds from the local Dockerfile in ACR — the
   image content is identical and no local Docker/Podman daemon is required.
2. **Push the existing local image** (when the user wants the exact local build,
   or `az acr build` is unavailable). Tag and push the locally-built image
   directly, matching the local bootstrap tag convention `<tool>:latest`:
   ```pwsh
   az acr login --name <acr-name>
   docker tag <tool>:latest <acr>.azurecr.io/<tool>:latest
   docker push <acr>.azurecr.io/<tool>:latest
   # Podman equivalent: podman tag <tool>:latest <acr>.azurecr.io/<tool>:latest; podman push <acr>.azurecr.io/<tool>:latest
   ```
   If the expected local image is missing, fall back to path 1.

Either path is followed by the same manifest rewrite, ARM registration, and
AcrPull grant (steps 3–6 below). **Never** push to any registry other than the
ACR chosen in Step 7c.2.

**Do not** use `runSubagent agentName='microsoft-foundry'`. That skill is
not registered as a subagent — the call fails with "Requested agent
'microsoft-foundry' not found". The skill is azd-oriented and assumes a
`.foundry/` overlay that catalog agents don't have. Execute the build
pipeline directly:

For each `tools/<Tool>/` subfolder under `discovery_catalog/<name>/` that
has a `Dockerfile`:

1. **Build + push in one shot** (preferred — uses ACR cloud build, no
   local Docker required):
   ```pwsh
   az acr build --registry <acr-name> `
                --image <tool>:latest `
                --image <tool>:sha-<gitshort> `
                discovery_catalog/<name>/tools/<Tool>/
   ```

   **Windows console crash — build still succeeds (observed).** On Windows,
   `az acr build` streams the remote build log through `colorama` and often
   dies client-side with
   `UnicodeEncodeError: 'charmap' codec can't encode characters ...`
   (cp1252). **This is a log-streaming failure only — the server-side ACR
   build keeps running and usually completes.** Do NOT treat the traceback
   as a build failure and do NOT immediately rebuild. Instead:
   - Set `$env:PYTHONIOENCODING = 'utf-8'` (and, when practical,
     `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`) *before*
     invoking `az acr build` to avoid the crash in the first place.
   - If it already crashed, capture the queued run id from the log
     (`Queued a build with ID: <id>`) and poll for completion instead of
     rebuilding:
     ```pwsh
     $env:PYTHONIOENCODING = 'utf-8'
     do {
       Start-Sleep -Seconds 20
       $run = az acr task list-runs --registry <acr-name> --top 10 -o json |
              ConvertFrom-Json | Where-Object { $_.runId -eq '<id>' }
       $status = $run.status
     } while ($status -eq 'Running')
     # $status is 'Succeeded' / 'Failed'
     ```
     Note: `az acr task list-runs --run-id <id>` can return empty; filter the
     `--top N` list client-side by `runId` instead.
   - Confirm the tags landed: `az acr repository show-tags --name <acr-name>
     --repository <tool> -o tsv`.

2. **Fallback** (only when `az acr build` is unavailable or fails with a
   clear "use local build" message):
   ```pwsh
   az acr login --name <acr-name>
   docker build -t <acr>.azurecr.io/<tool>:latest discovery_catalog/<name>/tools/<Tool>/
   docker push <acr>.azurecr.io/<tool>:latest
   ```

3. **Rewrite the manifest** so future re-deployments are reproducible:
   - `discovery_catalog/<name>/tools/<Tool>/tool.yaml` → set
     `infra[].image.acr` to the pushed reference (e.g.
     `mdqacr.azurecr.io/<tool>:latest`). Replace any `{name}` placeholder
     with the actual ACR name.
   - **Normalize `code_environments[].language` to `python3` (not `python`).**
     The tool ARM PUT accepts `python`, but the Foundry agent-binding step
     in 7e then fails with a bare `provisioningState=Failed` (no error text
     in `GetAgent`). Every working catalog container tool (e.g. `ambertools`,
     `crest`) uses `python3`; Foundry derives the generated function name
     `<tool>-Executepython3Code` from it. If the local `tool.yaml` says
     `language: python`, change it to `python3` here before registering.
   - Preserve all other fields and YAML formatting.

4. **Register the tool as a Discovery ARM resource.** The Discovery MCP
   does not surface a `CreateDiscoveryTool` tool — register via ARM API
   directly.

   **CRITICAL: `properties.definitionContent` MUST be a JSON _object_, not a
   YAML/JSON _string_.** Passing the raw `tool.yaml` text
   (`Get-Content ... -Raw`) fails with
   `HttpRequestPayloadAPISpecValidationFailed` /
   `InvalidType: Expected type object but found type string. Paths in
   payload: '$.properties.definitionContent'`. Convert the YAML into an
   object graph first. If `powershell-yaml` is unavailable (common), build
   the object explicitly with `[ordered]@{}` mirroring `tool.yaml`, then
   `ConvertTo-Json` the whole payload. Also write the body to a temp file
   and pass it with `--body "@<file>"` (avoids terminal quoting/echo
   truncation), and set `$env:PYTHONIOENCODING = 'utf-8'`.
   ```pwsh
   # $def mirrors tool.yaml as an object (name, description, version,
   # category, license, infra[], code_environments[]). Example shape:
   $def = [ordered]@{
     name        = '<tool>'
     description = '<tool description>'
     version     = '<tool-version-from-tool.yaml>'
     category    = 'Scientific Computing'
     license     = 'MIT'
     infra       = @(
       [ordered]@{
         name       = 'worker'
         infra_type = 'container'
         image      = [ordered]@{ acr = '<acr>.azurecr.io/<tool>:latest' }
         compute    = [ordered]@{ <min_resources/max_resources/...> }
       }
     )
     code_environments = @(
       [ordered]@{ language = 'python3'; command = 'python "/{{scriptName}}"'; description = '...'; infra_node = 'worker' }
     )
   }
   $payload = [ordered]@{
     location   = '<region>'
     tags       = [ordered]@{ category = 'Scientific Computing' }
     properties = [ordered]@{ version = '<tool-version>'; definitionContent = $def }
   }
   $bodyFile = Join-Path $env:TEMP 'dc-tool-put.json'
   $payload | ConvertTo-Json -Depth 30 | Set-Content -Path $bodyFile -Encoding UTF8
   $env:PYTHONIOENCODING = 'utf-8'
   az rest --method PUT `
     --uri "https://management.azure.com/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Discovery/tools/<tool>?api-version=2026-06-01" `
     --headers "Content-Type=application/json" `
     --body "@$bodyFile"
   ```
   To learn the exact object schema for a tool type, call `GetDiscoveryTool`
   on any existing working tool in the same workspace and mirror its
   `properties.definitionContent`.
   Poll provisioning state via `GetDiscoveryTool` until `Succeeded`.

5. **Grant AcrPull** to the workspace's user-assigned managed identity (the
   `workspaceIdentity.principalId` from `GetWorkspace`) on the ACR:
   ```pwsh
   az role assignment create --assignee <principalId> `
                             --role AcrPull `
                             --scope /subscriptions/<sub>/resourceGroups/<acr-rg>/providers/Microsoft.ContainerRegistry/registries/<acr>
   ```
   Treat "already exists" as success.

6. Record `$builtToolIds` (map `toolName → ARM resource ID`) and the image
   digests for the Step 8 summary.

#### 7e. Create the agent in the Discovery project via UpsertAgent

This is the single mechanism that creates the agent in the Discovery
project — there is no separate "Foundry hosted prompt agent create" step.
The Discovery `UpsertAgent` MCP tool does both Discovery registration and
the Foundry-side wiring.

1. **Extract the instructions block from the
   `.github/agents/<name>.agent.md` companion.** The Copilot companion's
   markdown body is the **source of truth for the prompt**, for **both**
   tool-bearing and toolless agents. Source `instructions` from that file
   via `Get-AgentMdInstructions` (defined in Step 4c.LTD), which strips the
   YAML frontmatter and any auto-generated container-bootstrap preamble.
   Promoting the companion body keeps the local Copilot subagent and the
   cloud Discovery agent in lockstep — whatever the user tuned locally is
   what gets deployed.

   ```pwsh
   # Same helper defined in Step 4c.LTD.
   $companion    = ".github/agents/$name.agent.md"
   $instructions = Get-AgentMdInstructions $companion

   # Tool-bearing promote: the local companion may still reference the tool as
   # a LOCAL Podman/Docker image (build context, image tag, image inspect).
   # The cloud has no local runtime — rewrite those references to point at the
   # deployed Discovery tool(s) instead. Requires the tool ARM + its ACR image
   # to already exist (Step 7c pre-flight / Step 7d build+push).
   if ($agentHasCatalogFolder[$name]) {
     $toolNames = @(Get-ChildItem "discovery_catalog/$name/tools" -Directory -ErrorAction SilentlyContinue |
                    ForEach-Object { $_.Name })
     if ($toolNames.Count -gt 0) {
       $instructions = Convert-PromoteInstructionsForTool -Instructions $instructions -ToolNames $toolNames
     }
   }

   # SANITY-CHECK the extracted body length BEFORE UpsertAgent. A tool-bearing
   # or otherwise real prompt should be thousands of chars. A result of only a
   # few hundred chars almost always means the CRLF regex bug (a bare
   # `\n---\n` that failed to match a CRLF companion) deleted the body. Abort
   # and fix the extraction rather than deploying a stub.
   if ($instructions.Length -lt 500) {
     throw "Extracted instructions for '$name' are only $($instructions.Length) chars — likely the CRLF regex bug. Fix Get-AgentMdInstructions / Convert-PromoteInstructionsForTool to use '\r?\n---\r?\n' and re-extract before UpsertAgent."
   }

   # name + description ALSO come from the companion frontmatter (same source
   # of truth as instructions), NOT from discovery_catalog/<name>/agent.yaml.
   $displayName = Get-AgentMdFrontmatterValue $companion 'name'
   if ([string]::IsNullOrWhiteSpace($displayName)) { $displayName = $name }
   $description = Get-AgentMdFrontmatterValue $companion 'description'
   if ([string]::IsNullOrWhiteSpace($description) -and (Test-Path "discovery_catalog/$name/agent.yaml")) {
     # Fallback only if the companion has no description.
     $description = (Get-Content "discovery_catalog/$name/agent.yaml" -Raw) # then parse agent.yaml#description
   }
   # Foundry caps description at 512 chars — truncate before UpsertAgent.
   if ($description.Length -gt 512) { $description = $description.Substring(0, 512).TrimEnd() }
   ```

   For a **tool-bearing** promote, the cloud instructions **must not**
   reference any local container image. The `Convert-PromoteInstructionsForTool`
   helper (Step 4c.LTD) removes the auto-generated bootstrap preamble, scrubs
   any residual `podman`/`docker` `build`/`pull`/`push`/`image inspect` lines
   and `discovery_catalog/.../tools/...` build-context references, and appends
   a short "Tool execution (Microsoft Discovery)" note pointing at the deployed
   Discovery tool(s) by name. **Before** calling `UpsertAgent`, confirm the
   tool is actually usable in the cloud: every tool the agent declares must
   have returned `provisioningState=Succeeded` from the Step 7c
   `GetDiscoveryTool` pre-flight (or been built + pushed + registered in Step
   7d), with its container image present in the workspace's ACR. Do not deploy
   a tool-bearing agent whose Discovery tool / ACR image is missing — bind the
   tool first, then promote.

   Do **NOT** read `instructions` **or `description`** from
   `discovery_catalog/<name>/agent.yaml` — the `.agent.md` companion
   supersedes both. (`agent.yaml` is still used only for the tool subtree
   and `metadata.yaml#associated_tools`.)

   Field sourcing summary:

   - **`instructions`** — always the `.github/agents/<name>.agent.md`
     companion body via `Get-AgentMdInstructions` (both buckets). For a
     **tool-bearing** agent, additionally pass the result through
     `Convert-PromoteInstructionsForTool` so the cloud prompt references the
     deployed Discovery tool(s) instead of any local Podman/Docker image.
   - **`name` / `description`** — for **both** buckets, read from the
     `.github/agents/<name>.agent.md` companion's YAML frontmatter via
     `Get-AgentMdFrontmatterValue` (`name` / `description`), **not** from
     `discovery_catalog/<name>/agent.yaml`. This keeps the deployed
     Discovery agent's display name and description in lockstep with the
     locally-tuned companion. Apply the 512-char truncation to
     `description` (see Step 7e.4). If the companion frontmatter has no
     `description`, fall back to `agent.yaml#description` (then still
     truncate).
   - **`toolIds`** — the pre-existing / built tool ARM IDs for a
     tool-bearing agent; empty for a toolless agent.

   **Fallback (upstream `Discovery` target only).** The upstream-sourced
   `Discovery` path does not generate a `.github/agents/<name>.agent.md`
   companion (Step 6 runs for `Local` only). If the companion file does
   **not** exist, fall back to reading the YAML block scalar
   (`instructions: |-`) from `discovery_catalog/<name>/agent.yaml`: read the
   full file, slice the lines between `instructions: |-` and the next
   top-level key (e.g. `discoveryExtensions:`), and strip the 2-space
   indent. PowerShell's `ConvertFrom-Yaml` (PSYaml module) is fine if
   available; otherwise the line-slice + indent-strip approach works:
   ```pwsh
   $companion = ".github/agents/$name.agent.md"
   if (Test-Path $companion) {
     $instructions = Get-AgentMdInstructions $companion
   } else {
     $lines = Get-Content discovery_catalog/$name/agent.yaml
     # find indices of 'instructions: |-' and the next top-level key
     $body = $lines[$start..$end] | ForEach-Object {
         if ($_.Length -ge 2 -and $_.Substring(0,2) -eq '  ') { $_.Substring(2) } else { $_ }
     }
     $instructions = $body -join "`n"
   }
   ```

   **Preserve all `{{templateVariables}}`** (`{{workflowContext}}`,
   `{{agentTeam}}`, `{{nodePoolContext}}`, `{{dataHandlingContext}}`,
   tool-id placeholders like `{{alphafoldToolId}}`, model placeholder
   `{{CHAT-MODEL}}`). These are filled in by the Discovery engine at
   invocation time.

2. **Pick a chat model deployment.** Call `ListChatModelDeployments`
   (via `Invoke-DiscoveryMcp`) against the workspace and apply this
   decision tree — **prefer auto-pick over asking**, every prompt costs
   a round-trip:
   - Filter to deployments with `provisioningState == 'Succeeded'`
     whose `modelName` starts with `gpt-5` (preferred) or equals `gpt-4o`
     (fallback). Sort by `systemData.lastModifiedAt` descending.
   - **Auto-pick the top candidate without asking** when:
     - The filtered list has exactly one entry, OR
     - The top candidate's `lastModifiedAt` is strictly newer than every
       other candidate's. (No tie at the top.)
   - **Only ask the user via `vscode_askQuestions`** when there are 2+
     candidates with the same most-recent `lastModifiedAt`, OR when no
     deployment matches the `gpt-5* / gpt-4o` filter (rare — fall back
     to all `Succeeded` deployments and ask).
   - Announce the auto-picked choice in the Step 8 summary so the user
     can see what was selected.

3. **Assemble `toolIds`.** Merge `$preExistingToolIds` (Step 7c) with
   `$builtToolIds` (Step 7d) into a comma-separated list of ARM resource
   IDs. For **toolless** agents this is empty — pass an empty string (or
   omit `toolIds`); do not fabricate a tool binding.

4. **Call `UpsertAgent`** (via `Invoke-DiscoveryMcp`). Required values:
   - `subscriptionId`, `resourceGroupName`, `workspaceName`, `projectName`
   - `agentName` (= agent folder name, kebab-case)
   - `kind`: `prompt` (default for catalog agents — they're all prompt
     agents) or `workflow` if `agent.yaml#kind == 'workflow'`
   - `description`: the companion frontmatter `description` (via
     `Get-AgentMdFrontmatterValue ".github/agents/$name.agent.md" 'description'`),
     falling back to `agent.yaml#description` only if the companion has none.
     **Truncate to 512 chars max.** Foundry caps the agent `description` at
     512 characters; a longer value causes a fast bare
     `provisioningState=Failed` (with `foundryDetails=null` and no error text
     in `GetAgent`). This is NOT a tool-binding failure. Trim to <=512 before
     calling `UpsertAgent` (e.g. drop a trailing scope sentence).
     `GetAgentOperation(operationId)` returns the real error
     (`maxLength: Value should be at most 512 characters` on `/description`)
     if you need to confirm.
   - `instructions`: the extracted string from step 1
   - `model`: the chat model deployment name from step 2
   - `temperature`: `agent.yaml#model.options.temperature` (default 0)
   - `topP`: `agent.yaml#model.options.topP` (default 0)
   - `toolIds`: comma-separated ARM IDs from step 3
   - `humanInTheLoop`: from `agent.yaml#discoveryExtensions.humanInTheLoop`
     (default `Disabled`)
   - `discoveryExtensions`: JSON string of any extensions
     (`{"disableDataHandlingTools": false}` is a safe default)

5. **Poll `GetAgent` for `provisioningState=Succeeded`.** `UpsertAgent`
   returns `{id, status, agentName}` where `id` is an operationId. Prefer
   `GetAgent` provisioningState polling for the happy path (the
   `GetAgentOperation` MCP tool has historically been flaky, though it can
   still return the real error — see the recovery notes below). Use the
   extracted `Wait-DiscoveryAgentReady` helper, which polls `GetAgent` and
   watches `provisioningState`:

   ```pwsh
   Wait-DiscoveryAgentReady -ProxyPath $proxy `
       -SubscriptionId $sub -ResourceGroupName $rg `
       -WorkspaceName $ws -ProjectName $proj `
       -AgentName $agentName -TimeoutSeconds 300
   ```

   States to handle:
   - `Creating` / `Updating` / `Accepted` → helper keeps polling.
   - `Succeeded` → helper returns the parsed agent object; record
     `$createdAgentId` for Step 8 summary.
   - `Failed` → helper throws with the full payload; surface verbatim
     and do not retry blindly.

   **When a tool is bound and `GetAgent` reports `Failed` fast (~5–10 s)
   with `foundryDetails=null` and no error text**, the failure is almost
   always the tool binding, not the prompt. Diagnose and recover as follows
   (this exact sequence recovered a real run):
   1. **Confirm it's the tool, not the instructions.** Re-`UpsertAgent`
      once *without* `toolIds` (same model + instructions). If that
      Succeeds, the prompt is fine and the tool binding is the culprit.
   2. **Check the tool's `language`.** Call `GetDiscoveryTool` and compare
      `code_environments[].language` against a working container tool in the
      same workspace. If it's `python` (or anything other than `python3`),
      re-register the tool ARM with `language: python3` (Step 7d.3–7d.4) and
      wait for `GetDiscoveryTool` to report `Succeeded` again.
   3. **Allow propagation before rebinding.** After the tool ARM flips to
      `Succeeded`, the Foundry-side tool definition can still be stale for
      ~30–60 s. An immediate `UpsertAgent` with the tool may still `Fail`.
      Wait ~30–60 s, then re-`UpsertAgent` with `toolIds` and re-poll. A
      second attempt typically Succeeds.
   4. **Get the real error when you need it.** Contrary to older guidance,
      `GetAgentOperation` *can* return the actual result/error. After an
      `UpsertAgent`, capture the returned `id` (operationId) and call
      `GetAgentOperation` with `operationId=<id>` (plus the sub/rg/ws/proj/
      agentName args). It returns `{status, error, result}` — use `error`
      for the failure detail and `result` for the provisioned agent. Still
      prefer `Wait-DiscoveryAgentReady` (GetAgent polling) for the happy
      path; reach for `GetAgentOperation` only when GetAgent gives a bare
      `Failed`.

   Typical provisioning takes 10–60 s. If `Wait-DiscoveryAgentReady`
   times out at 300 s, the agent almost certainly did succeed — verify
   with one `ListAgents` call before declaring failure.

6. **Verify** with `ListAgents` (or `GetAgent`) to confirm the agent
   appears in the project with `provisioningState=Succeeded` and the
   expected `toolIds`.

#### 7f. (Optional) Local Discovery agent runtime registration

The cloud-side agent created in Step 7e is **fully usable** via the
Discovery web studio and the Discovery MCP `CreateResponse` tool (called via `Invoke-DiscoveryMcp`) without this
step. Only proceed if the user explicitly wants the agent to appear in the
local Discovery extension's agent picker (different scope from the cloud
project).

If proceeding:

1. Call `agents` with `action: tools.list` to discover which catalog tools
   match the agent's `discoveryExtensions.tools` references.
2. Call `agents` with `action: create`, passing:
   - `name`: the agent folder name (kebab-case)
   - `description`: from `agent.yaml#description`
   - `systemPrompt`: from `agent.yaml#instructions`
   - `toolGrants`: declarative grants assembled from step 1
3. Optionally call `agents` with `action: registry.refresh` so the new entry
   appears in `agents list` immediately.

**Do not** call `agents` with `action: run.start` from this skill —
registration is the goal; running the agent is a separate user action.

Ask the user once (default: skip) before performing this step.

#### 7g. Rules and guard-rails

- **Local files are the source of truth.** For a **tool-bearing** agent,
  never deploy one whose `discovery_catalog/<name>/` folder is missing or
  only partially copied. A **toolless** promote agent legitimately has **no**
  `discovery_catalog/<name>/` folder — its source of truth is the
  `.github/agents/<name>.agent.md` companion; require that companion to
  exist and to yield a non-empty instructions body before deploying.
- **Instructions AND description come from the
  `.github/agents/<name>.agent.md` companion.** For **both** buckets in the
  `LocalToDiscovery` (promote) path, the prompt body deployed to Discovery is
  the companion's markdown body (via `Get-AgentMdInstructions`) and the
  agent `name` / `description` are the companion frontmatter values (via
  `Get-AgentMdFrontmatterValue`), never `discovery_catalog/<name>/agent.yaml`.
  Require a non-empty instructions body from the companion before deploying,
  and truncate `description` to 512 chars (Foundry cap). Only the upstream
  `Discovery` target (no companion) falls back to `agent.yaml#instructions` /
  `agent.yaml#description` (Step 7e.1).
- **Cloud instructions for tool-bearing promotes must reference the
  Discovery tool, not a local image.** When a promoted agent has a
  `discovery_catalog/<name>/tools/<Tool>/` folder, pass its instructions
  through `Convert-PromoteInstructionsForTool` (Step 4c.LTD) so the deployed
  prompt drops every local Podman/Docker build/inspect/pull/push reference
  and points at the deployed Discovery tool(s) by name. The cloud has no
  local container runtime — never deploy local image tags or build contexts.
  Confirm each declared tool is `provisioningState=Succeeded` with its image
  present in the workspace's ACR (Step 7c/7d) **before** `UpsertAgent`.
- **Tool detection is mandatory for tool-bearing agents.** Always run Step
  7c `GetDiscoveryTool` pre-flight before asking ACR/RG questions or
  building images. If you prompt the user for an ACR that turns out to be
  irrelevant because the tool already exists, you've wasted their time.
  Toolless agents skip 7c/7d entirely.
- **Idempotency.** If an image tag already exists in ACR with the same
  digest, do not rebuild. If a hosted agent with the same name already
  exists in the Foundry project, prefer `update` over `create` and ask the
  user once before overwriting.
- **Never push to public registries.** Only the ACR named in step 7c.2 is a
  valid push target. Reject any attempt to push to `docker.io`, `ghcr.io`,
  or any other registry.
- **No secrets through `vscode_askQuestions`.** If the Foundry deployment
  requires a token the user has not already configured via `az login`, stop
  and ask them to authenticate in the terminal.
- **Bail on RBAC failures.** If the Foundry-managed identity cannot be
  granted `AcrPull` on the registry, stop and report the missing
  permission. Do not retry by escalating privileges.
- **Always preserve `discovery_catalog/<name>/` after deployment.** Step 7
  may rewrite `tool.yaml#infra.image.acr` in place — that's fine — but it
  must not delete the local folder or its `tools/` subtree.
- **`microsoft-foundry` is a skill, not a subagent.** Do not call
  `runSubagent agentName='microsoft-foundry'`. Execute the deploy
  pipeline directly using Discovery MCP + `az` CLI as described above.
- **Tool ARM `definitionContent` is an object, not a string.** Build it
  with `[ordered]@{}` (or `ConvertFrom-Yaml`) and `ConvertTo-Json`; never
  pass raw `tool.yaml` text. A string payload fails with
  `InvalidType: Expected type object but found type string`.
- **Container tools must declare `language: python3`.** `python` passes the
  tool ARM PUT but breaks Foundry agent-binding (bare `Failed`, no error).
- **Give tool changes ~30–60 s to propagate** before binding them to an
  agent; an immediate `UpsertAgent` after a tool re-register can still
  `Fail` even though the tool shows `Succeeded`.
- **`az acr build` may crash the Windows console but still build.** Set
  `$env:PYTHONIOENCODING='utf-8'` before calling it; if it crashed, poll
  `az acr task list-runs` for the queued run id instead of rebuilding.

### Step 8 — Cleanup and summary

1. Remove the temp clone directory: `Remove-Item -Recurse -Force $work`.
2. Print a structured summary to chat:
   - **Selection mode** (All / Specific / By group) and **resolved selection** (N agents)
   - **Deployment target** (Local / Discovery / LocalToDiscovery)
   - **Catalog folders created** (N — `discovery_catalog/<name>/` did not exist locally before this run; list names)
   - **Catalog folders refreshed** (N — `discovery_catalog/<name>/` was overwritten with the latest upstream copy; list names)
   - **Catalog folders skipped** (N — name not present in `agents/` upstream; e.g. removed from the catalog)
   - **Companions already present** (N — `.github/agents/<name>.agent.md` existed before this run; from `$existingLocalAgents`. These were re-generated, not skipped.)
   - **Copilot agents generated** (N `.github/agents/*.agent.md` files written — only when target == `Local`. Includes both fresh files and re-generations.)
   - **Copilot agents skipped** (N, with reason — missing `agent.yaml`, empty `instructions`, etc.)
  - **Container bootstrap preambles emitted** (N agents that had at least one `tools/*/Dockerfile` upstream)
   - **Pre-existing tool ARMs detected** (N, list `toolName → ARM ID` — image build skipped for these — only when target is a Discovery-class target)
   - **Tool images built and pushed** (N images pushed to `<acr>.azurecr.io` — only when target == `Discovery` and at least one tool was missing)
   - **Tool ARMs registered** (N new `Microsoft.Discovery/tools` resources created — only when target is a Discovery-class target)
   - **Discovery agents provisioned** (N agents created/updated in the Discovery project via `UpsertAgent` — only when target is a Discovery-class target)
   - **Local Discovery runtime entries created** (N agents registered via `agents action=create` — only when user opted into Step 7f)
   - **Deployment failures** (N, with the failing agent name and error message — never silently drop)

When `$deployTarget == 'Local'`, this skill does NOT build or pull local
container images. Image builds are deferred to each generated `.agent.md` at
invocation time and are conditional on the image being absent.

When `$deployToCloud` is true (`$deployTarget` is `Discovery` or
`LocalToDiscovery`), Step 7c pre-flights each tool against
the workspace's RG via `GetDiscoveryTool`. If every tool already exists
(`provisioningState=Succeeded`), Step 7d is skipped entirely — no ACR
prompts, no image builds, no RBAC. Step 7e then provisions the agent in
the Discovery project via `UpsertAgent` + `GetAgent` provisioningState
polling (the `GetAgentOperation` MCP tool is broken in practice — see the
Scripted MCP invocation section above). Step
7f (local runtime registration) is optional and skipped by default.

## Verification checklist

After adding the agents, for at least one newly-created agent, confirm:

- [ ] `discovery_catalog/<name>/agent.yaml` exists and starts with `kind: prompt`
- [ ] `discovery_catalog/<name>/metadata.yaml` lists `associated_tools` pointing at `agents/<name>/tools/<Tool>`
- [ ] `discovery_catalog/<name>/tools/<Tool>/Dockerfile` exists
- [ ] `discovery_catalog/<name>/tools/<Tool>/tool.yaml` parses as YAML and contains an `infra:` block with `image.acr`

When `$deployTarget == 'Local'`:

- [ ] `.github/agents/<name>.agent.md` exists, starts with `---`, and its frontmatter `name:` matches `agent.yaml#name`
- [ ] The body of `.github/agents/<name>.agent.md` is the (de-indented) contents of `agent.yaml#instructions`, preceded by the container bootstrap preamble when at least one `tools/*/Dockerfile` exists
- [ ] The hand-authored Copilot agents (`batteries-included`, `bookshelf-researcher`, `project-setup-orchestrator`) are untouched

When `$deployToCloud` is true (`$deployTarget` is `Discovery` or `LocalToDiscovery`):

- [ ] Every `tools/<Tool>/Dockerfile` in `$selected` has produced an image at `<acr>.azurecr.io/<tool>:latest` (verify with the Azure MCP or `az acr repository show-tags`)
- [ ] The corresponding `tool.yaml#infra.image.acr` field has been updated to point at the pushed tag
- [ ] Each agent appears in `agents action=list` with the expected name and tool grants
- [ ] A hosted prompt agent with the same name exists in the configured Foundry project

## Things this skill must NOT do

- Do not edit `agent.yaml` or `metadata.yaml` contents during the local copy step — copy verbatim. (Step 7 may rewrite `tool.yaml#infra.image.acr` after a successful ACR push; that is allowed.)
- Do not generate placeholder Dockerfiles for tools that lack one upstream.
- **Do not run local `podman build|pull|push` or `docker build|pull|push` directly from this skill when `$deployTarget == 'Local'`.** Local image bootstrap is delegated to the generated agents and must happen lazily at invocation time only when the image is missing.
- When `$deployTarget == 'Local'`, do not touch Azure Container Registry, Microsoft Foundry, or the Discovery agent registry.
- Do not delete existing local agents that aren't in upstream.
- Do not create `.md` documentation of the add operation — print the summary to chat.
- Do not overwrite or delete `.github/agents/*.agent.md` files whose stem does **not** correspond to a `discovery_catalog/<name>/` folder (those are hand-authored Copilot agents).

## Embedded Discovery MCP scripts

These embedded scripts are the authoritative source for the generated
`.vscode/discovery-mcp-proxy.ps1` and `.vscode/Invoke-DiscoveryMcp.ps1` files.
Do not require sibling `.ps1` files next to this skill. Extract these blocks
verbatim with the Step 4d bootstrap before making Discovery MCP calls.

<!-- BEGIN:embedded-discovery-mcp-proxy.ps1 -->
```powershell
#Requires -Version 7
<#
.SYNOPSIS
  Local stdio<->HTTP proxy for the Microsoft Discovery remote MCP server.

.DESCRIPTION
  VS Code launches this script as a stdio MCP server. It transparently:
  1. Mints an Entra access token for https://discovery.azure.com via
     `az account get-access-token`, using whatever tenant + subscription
     the active `az` session is signed into.
  2. Forwards every newline-delimited JSON-RPC message from stdin to
     https://mcp.discovery.azure.com/mcp via HTTPS POST, attaching the
     bearer token and the Mcp-Session-Id header.
  3. Streams the response back to stdout. Handles both `application/json`
     (single response) and `text/event-stream` (SSE) responses.
  4. On HTTP 401 (token expired or wrong tenant), automatically mints a
     fresh token from `az` and retries the request once. No user
     interaction, no clipboard, no command-palette prompt.

  Replaces the legacy `inputs[type=promptString]` flow that required the
  user to paste a token into a command-palette input every time the MCP
  server restarted.

.NOTES
  - Requires PowerShell 7+ (uses Invoke-WebRequest -SkipHttpErrorCheck).
  - Requires `az` CLI on PATH with an active session (`az login`).
  - All diagnostic output goes to STDERR so it does not corrupt the MCP
  stdio JSON-RPC channel on STDOUT.
#>

[CmdletBinding()]
param(
  [string]$Endpoint = 'https://mcp.discovery.azure.com/mcp',
  [string]$Resource = 'https://discovery.azure.com'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Diag([string]$Message) {
  [Console]::Error.WriteLine("[discovery-mcp-proxy] $Message")
}

function New-DiscoveryToken {
  $azPath = (Get-Command az -ErrorAction SilentlyContinue)?.Source
  if (-not $azPath) {
    throw "az CLI not found on PATH. Install Azure CLI and run 'az login'."
  }
  $tok = & az account get-access-token --resource $Resource --query accessToken -o tsv 2>$null
  if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^(ERROR|AADSTS)') {
    throw "Failed to mint Discovery access token via az. Run 'az login --tenant <tenant>' and try again."
  }
  return $tok.Trim()
}

$script:Token = $null
$script:SessionId = $null

try {
  $script:Token = New-DiscoveryToken
  Write-Diag "Initial token minted (len=$($script:Token.Length))."
} catch {
  Write-Diag "FATAL: $($_.Exception.Message)"
  exit 1
}

function Invoke-McpRequest {
  param([string]$Body)

  $headers = @{
    'Authorization' = "Bearer $script:Token"
    'Accept'        = 'application/json, text/event-stream'
  }
  if ($script:SessionId) {
    $headers['Mcp-Session-Id'] = $script:SessionId
  }

  $attempt = 0
  while ($true) {
    $attempt++
    try {
      $resp = Invoke-WebRequest -Uri $Endpoint `
                     -Method Post `
                     -Body $Body `
                     -ContentType 'application/json' `
                     -Headers $headers `
                     -SkipHttpErrorCheck `
                     -ErrorAction Stop
    } catch {
      Write-Diag "POST exception: $($_.Exception.Message)"
      return $null
    }

    if ($resp.StatusCode -eq 401 -and $attempt -eq 1) {
      Write-Diag "401 from Discovery MCP; refreshing token and retrying."
      try {
        $script:Token = New-DiscoveryToken
        $headers['Authorization'] = "Bearer $script:Token"
        continue
      } catch {
        Write-Diag "Token refresh failed: $($_.Exception.Message)"
        return $null
      }
    }

    foreach ($k in $resp.Headers.Keys) {
      if ($k -ieq 'Mcp-Session-Id') {
        $val = $resp.Headers[$k]
        if ($val -is [array]) { $val = $val[0] }
        if ($val) { $script:SessionId = $val }
        break
      }
    }

    if ($resp.StatusCode -ge 400) {
      Write-Diag "HTTP $($resp.StatusCode) from Discovery MCP: $($resp.Content)"
    }
    return $resp
  }
}

function Write-McpLine([string]$Line) {
  if ([string]::IsNullOrWhiteSpace($Line)) { return }
  [Console]::Out.WriteLine($Line)
  [Console]::Out.Flush()
}

function Emit-Response($Resp) {
  if (-not $Resp) { return }
  if ($Resp.StatusCode -eq 202) { return }
  if ([string]::IsNullOrEmpty($Resp.Content)) { return }

  $ctype = ''
  foreach ($k in $Resp.Headers.Keys) {
    if ($k -ieq 'Content-Type') {
      $v = $Resp.Headers[$k]
      if ($v -is [array]) { $v = $v[0] }
      $ctype = [string]$v
      break
    }
  }

  if ($ctype -like 'text/event-stream*') {
    foreach ($block in ($Resp.Content -split "(?:`r?`n){2,}")) {
      $dataLines = @()
      foreach ($line in ($block -split "`r?`n")) {
        if ($line -match '^data:\s?(.*)$') { $dataLines += $matches[1] }
      }
      if ($dataLines.Count -gt 0) {
        Write-McpLine (($dataLines -join "`n").Trim())
      }
    }
  } else {
    $compact = ($Resp.Content -replace "`r?`n", '').Trim()
    Write-McpLine $compact
  }
}

Write-Diag "Proxy ready. Endpoint=$Endpoint"

try {
  while ($null -ne ($line = [Console]::In.ReadLine())) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $resp = Invoke-McpRequest -Body $line
    Emit-Response $resp
  }
} catch {
  Write-Diag "Main loop exception: $($_.Exception.Message)"
  exit 2
}

Write-Diag "stdin closed; exiting cleanly."
```
<!-- END:embedded-discovery-mcp-proxy.ps1 -->

<!-- BEGIN:embedded-Invoke-DiscoveryMcp.ps1 -->
```powershell
#Requires -Version 7
<#
.SYNOPSIS
  Canonical helper to invoke any Microsoft Discovery MCP tool from scripted
  PowerShell, without depending on the VS Code MCP runtime surfacing the
  `mcp_microsoft-dis_*` tools mid-session.

.DESCRIPTION
  Spawns `discovery-mcp-proxy.ps1` as a stdio process, sends an MCP
  `initialize` + one `tools/call` per call in $Calls, and returns a hash
  keyed by JSON-RPC id (`'2'`, `'3'`, ...) whose values are the parsed
  response objects.

  This is the PREFERRED path for any MCP work this skill performs. The
  VS Code mcp.json registration is a nice-to-have for the user's future
  interactive sessions - do not block on it for scripted runs.

.EXAMPLE
  . "$PSScriptRoot\Invoke-DiscoveryMcp.ps1"
  $results = Invoke-DiscoveryMcp -ProxyPath "$workspaceRoot\.vscode\discovery-mcp-proxy.ps1" -Calls @(
    @{ name='ListAgents'; args=@{ subscriptionId=$sub; resourceGroupName=$rg; workspaceName=$ws; projectName=$proj } }
  )
  $r = $results['2']
  $txt = ($r.result.content | Where-Object { $_.type -eq 'text' } | Select-Object -ExpandProperty text) -join "`n"
  $obj = $txt | ConvertFrom-Json -Depth 50

.NOTES
  - Requires PowerShell 7+.
  - Each call is a single `tools/call`; results are returned as parsed
  JSON-RPC objects keyed by id. Inspect `$r.result.isError` for
  server-side tool errors (the JSON-RPC frame still succeeds in that
  case).
  - On HTTP 401, the proxy refreshes the `az` token automatically.
#>

function Invoke-DiscoveryMcp {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ProxyPath,
    [Parameter(Mandatory)][object[]]$Calls
  )

  if (-not (Test-Path $ProxyPath)) {
    throw "Discovery MCP proxy not found at $ProxyPath"
  }

  $msgs = @()
  $msgs += '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"add-agent-from-catalog","version":"1.0.0"}}}'
  $msgs += '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

  $id = 2
  foreach ($c in $Calls) {
    $payload = @{
      jsonrpc = '2.0'
      id      = $id
      method  = 'tools/call'
      params  = @{ name = $c.name; arguments = ($c.args ?? @{}) }
    } | ConvertTo-Json -Depth 30 -Compress
    $msgs += $payload
    $id++
  }

  $tmp = New-TemporaryFile
  try {
    ($msgs -join "`n") | Set-Content -Path $tmp.FullName -Encoding ascii
    $raw = Get-Content $tmp.FullName | pwsh -NoProfile -File $ProxyPath 2>$null
  } finally {
    Remove-Item $tmp.FullName -ErrorAction SilentlyContinue
  }

  $results = [ordered]@{}
  foreach ($line in $raw) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    try {
      $obj = $line | ConvertFrom-Json -Depth 50
    } catch { continue }
    if ($null -eq $obj.id) { continue }
    $results[[string]$obj.id] = $obj
  }
  return $results
}

function Get-DiscoveryMcpText {
  <#
  .SYNOPSIS
    Extract the text payload from a single MCP tool/call response object
    and parse it as JSON when possible.
  .DESCRIPTION
    Most Discovery MCP tools return their payload inside
    $r.result.content[].text as a JSON string. This helper concatenates
    those text blocks and (optionally) parses the result.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][object]$Response,
    [switch]$AsJson
  )
  if (-not $Response) { return $null }
  $texts = @()
  foreach ($c in $Response.result.content) {
    if ($c.type -eq 'text') { $texts += $c.text }
  }
  $blob = $texts -join "`n"
  if ($AsJson) {
    try { return $blob | ConvertFrom-Json -Depth 50 } catch { return $blob }
  }
  return $blob
}

function Wait-DiscoveryAgentReady {
  <#
  .SYNOPSIS
    Poll GetAgent until provisioningState == 'Succeeded' (or 'Failed').
  .DESCRIPTION
    Replaces the unreliable GetAgentOperation polling. The MCP server's
    GetAgentOperation often returns an opaque "An error occurred invoking
    'GetAgentOperation'." text even when UpsertAgent has succeeded - but
    GetAgent reliably reports provisioningState.
  #>
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)][string]$ProxyPath,
    [Parameter(Mandatory)][string]$SubscriptionId,
    [Parameter(Mandatory)][string]$ResourceGroupName,
    [Parameter(Mandatory)][string]$WorkspaceName,
    [Parameter(Mandatory)][string]$ProjectName,
    [Parameter(Mandatory)][string]$AgentName,
    [int]$TimeoutSeconds = 300,
    [int]$IntervalSeconds = 5
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    $results = Invoke-DiscoveryMcp -ProxyPath $ProxyPath -Calls @(
      @{ name='GetAgent'; args=@{ subscriptionId=$SubscriptionId; resourceGroupName=$ResourceGroupName; workspaceName=$WorkspaceName; projectName=$ProjectName; agentName=$AgentName } }
    )
    $r = $results['2']
    $obj = Get-DiscoveryMcpText -Response $r -AsJson
    if ($obj -and $obj.provisioningState) {
      if ($obj.provisioningState -eq 'Succeeded') { return $obj }
      if ($obj.provisioningState -eq 'Failed')    { throw "Agent '$AgentName' provisioning Failed: $($obj | ConvertTo-Json -Depth 10 -Compress)" }
    }
    Start-Sleep -Seconds $IntervalSeconds
  }
  throw "Timed out after ${TimeoutSeconds}s waiting for agent '$AgentName' to reach Succeeded."
}
```
<!-- END:embedded-Invoke-DiscoveryMcp.ps1 -->
- Do not add `tools:` frontmatter to generated `.agent.md` files — Discovery tool IDs don't map to Copilot tool names, and a wrong list silently disables tools.
- **Do not call `runSubagent agentName='microsoft-foundry'`.** That skill is not registered as a subagent in this workspace, and even when invoked directly it assumes an azd `.foundry/` overlay that catalog agents don't have. Execute the deploy pipeline inline via Discovery MCP (`GetDiscoveryTool`, `UpsertAgent`, `GetAgent` provisioningState polling) + `az` CLI, as documented in Steps 7c–7e.
- Do not push tool images to any registry other than the ACR named in Step 7c.2.
- Do not request secrets through `vscode_askQuestions`; require the user to authenticate to Azure with `az login` directly in the terminal when needed. Do not ask for GitHub authentication for the public `microsoft/discovery` catalog fetch.

## When to ask the user

Ask **once, up front**, in **this order** (the order matters — each answer
shapes the next prompt):

1. **Deployment target** (Step 4c) — Local Copilot only / Microsoft Discovery + Azure (from upstream) /
   Local app -> Microsoft Discovery + Azure (promote). Default =
   `Local Copilot only` (cheapest, fastest, fully local).
   This is the **first** user-facing prompt; everything else is scoped to
   the answer here.
2. **Discovery tenant + subscription + workspace + project** (Step 4d,
   only when target is `Discovery` or `LocalToDiscovery`) — install the Microsoft Discovery
   MCP server **without asking** if `agents action=registry.list` doesn't
   already succeed (the user opted into the Discovery + Azure path; the
   MCP is a hard prerequisite). Before starting the MCP server, prompt
   the user **once** (single `vscode_askQuestions` call, two questions)
   for the Azure **tenant ID** and **subscription ID** (Step 7a.2.5),
   then run `az login --tenant <id>` and `az account set --subscription
   <id>` on their behalf in a foreground terminal. Persist the choices to
   `/memories/repo/`. After `az` is ready, restart the MCP server, then
   present single-select prompts for workspace and project (sourced via
   `ListWorkspaces` /
   `ListProjects` calls (always via `Invoke-DiscoveryMcp`; never depend on the
   VS Code deferred `mcp_microsoft-dis_*` tools surfacing). Always list the existing agents in
   the chosen project before continuing, and confirm before moving on to
   the agent picker. **These four prompts (tenant, subscription,
   workspace, project) are mandatory on every Discovery run — never
   skip them based on saved values in `/memories/repo/`. Saved values
   are used only to mark the corresponding option as `recommended` in
   the picker.**
3. **Agent selection** (Step 4e) — present the All / Specific / By group
   prompt via `vscode_askQuestions`. This is mandatory; never default to
   adding the whole catalog without confirmation. When target ==
   `Discovery`, annotate options whose folder name matches an existing
   agent in the project (from step 2) with `[ALREADY IN PROJECT]` so the
   user knows what will be updated by `UpsertAgent`.
4. **Local runtime readiness** (Step 4f, only when target == `Local`) —
  detect Podman/Docker availability. If both are installed, ask once which
  runtime the user prefers (default `podman`). If only one is installed,
  auto-select it. If neither is installed, ask once whether to install
  Podman automatically; on yes run `winget install --id RedHat.Podman --accept-source-agreements --accept-package-agreements`, on no continue with a clear warning that container-based tools cannot run until Podman or Docker is installed.
5. **Overwrite conflicts** — if any folder in `$selected` already exists
   locally, ask once whether to overwrite. Default = no.
6. **Azure deployment configuration** (Step 7c.2, only when target == `Discovery`
   **and** Step 7c found at least one tool that needs building) —
   subscription, resource group, ACR, region. Foundry project is pre-filled
   from Step 4d; the user only overrides it if they explicitly need a
   different target. Ask all in a single `vscode_askQuestions` call. Pre-fill
   defaults from `az account show` and any prior values stored in
   `/memories/repo/`. **Skip entirely when every declared tool already
   exists as an ARM resource** (the common case for shared catalog images).
7. **Azure MCP install** (Step 7b, only when target is `Discovery` or `LocalToDiscovery`) — if a
   relevant Azure plugin is `metadata_only`, ask once whether to install it.
   Default = no (fall back to `az` CLI).
8. **Agent overwrite** (Step 7e) — if an agent with the same name already
   exists in the target Discovery project (visible from `ListAgents` in
   Step 4d), ask once before calling `UpsertAgent` (which will update the
   existing definition in place). Default = no.

Do NOT ask whether to pre-build local images when `$deployTarget == 'Local'` —
that step never builds images. Ask runtime readiness only (Step 4f).
Each generated agent will build its own image lazily on first invocation,
trying Podman first and Docker second, only if the image is not already present.

Do not launch a GitHub device-flow prompt in Step 2. The upstream
`microsoft/discovery` repository is public, so GitHub authentication is not
part of this workflow. `az login` in Step 7a.2.5 is still launched on the
user's behalf as soon as tenant + subscription are picked.

Otherwise run end-to-end without further prompting.





