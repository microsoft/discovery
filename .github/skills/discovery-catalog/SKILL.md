---
name: discovery-catalog
description: Inventory the contents of this Discovery catalog repo. Lists publishers, agents, starter-kits, and the tools shipped under each agent. Use this skill whenever the user asks what's in the catalog, who publishes what, what agents/tools/starter-kits exist, lists or counts of any of those, "show me the catalog", "do we have an agent for X", "what starter kits do we have", "list the publishers", "list tools per agent", or any inventory/discovery question about repo-resident assets — even if the user doesn't explicitly say the word "list".
allowed-tools: shell
---

# Discovery Catalog

## Compatibility

This skill is read-only and runs on Windows, macOS, and Linux through PowerShell. PowerShell 7+ (`pwsh`) is recommended for consistent table rendering, though the dispatcher also works in Windows PowerShell 5.1 with less polished wrapping.

## Overview

Read-only inventory of the Discovery catalog repo. One dispatcher script (`scripts/discovery-catalog.ps1`) supports list and item-inspection invocations:

| Invocation | What it lists |
|---|---|
| `discovery-catalog publishers` | Every publisher across `agents/` and `starter-kits/`, with per-publisher agent and starter-kit counts |
| `discovery-catalog agents` | Every agent in the catalog (one row per agent folder name) |
| `discovery-catalog agents list-tools` | Every agent **plus** the tools shipped under each agent's `tools/` folder |
| `discovery-catalog starter-kits` | Every starter kit (one row per kit folder name) |
| `discovery-catalog <agent-name> describe` | One agent with `Name, Publisher, Version, HasTool, Description` |
| `discovery-catalog <starterkit-name> describe` | One starter kit with `Name, Publisher, Version, Category, AgentCount, Description` |
| `discovery-catalog <agent-name> list-tools` | One agent with `Agent, Publisher, Version, ToolCount, Tools, Description` |

## Repo layout the script handles

The catalog uses a **flat** layout — one folder per agent or starter kit directly under the parent directory:

| Asset | Path pattern | Display |
|---|---|---|
| Agent | `agents/<agent-name>/` | `<agent-name>` |
| Starter kit | `starter-kits/<kit-name>/` | `<kit-name>` |
| Tool under an agent | `agents/<agent>/tools/<tool-name>/` | `<tool-name>` |

Inclusion rules:

- An "agent" is any folder containing an `agent.yaml`.
- A "starter kit" is any folder containing a `kit.json`.
- Folders without those files (shared helpers, README-only directories) are silently skipped.
- The `agents/tmp/` scratch directory used by the deployer skills is always skipped.

Publisher and party come from the asset's metadata, **not** from the folder location:

- For an agent: `metadata.yaml` → `publisher.name` (publisher) and `publisher.party` (`1p` / `3p`).
- For a starter kit: `kit.json` → `author.name` (publisher) and the top-level `party` field.

If `publisher.name` / `author.name` is missing, the publisher is reported as `(unspecified)`.

## When to Use

Use this skill whenever the user wants to know what is in the catalog. Trigger phrases include but are not limited to:

- *"What agents are in this repo?"* / *"List the agents"* / *"Show me the catalog"*
- *"Who are the publishers?"* / *"Which partners have agents?"*
- *"What starter kits do we have?"* / *"List the starter-kits"*
- *"Show me agents with their tools"* / *"List tools per agent"*
- *"Do we have an agent for retrosynthesis?"* (use `-Tag retrosynthesis`)
- *"Which agents are missing a tool?"* (use `-WithoutToolsOnly`)
- Before invoking `discovery-services-agent-deployer`, when the user isn't sure of the exact agent folder name

## Inputs

The skill is fully read-only and needs no Azure config. All inputs are positional or named parameters on `scripts/discovery-catalog.ps1`.

| Parameter | Position | Description | Default |
|---|---|---|---|
| `Command` | `0` (mandatory) | `publishers`, `agents`, `starter-kits`, or an agent/starter-kit name | — |
| `SubCommand` | `1` (optional) | `list-tools` (with `agents` or `<agent-name>`) or `describe` (with `<agent-name>` / `<starterkit-name>`) | empty |
| `-Format` | named | `Table`, `Markdown`, `Json`, or `Plain` | `Table` |
| `-Publisher` | named | Filter by publisher name (case-insensitive). Applies to `agents` and `starter-kits` | all |
| `-Tag` | named | Filter agents whose `metadata.yaml` includes this tag (`agents` only) | all |
| `-WithToolsOnly` | named | Only show agents that ship a `tools/` folder (`agents` only) | off |
| `-WithoutToolsOnly` | named | Only show agents missing a `tools/` folder (`agents` only) | off |

Invalid combinations exit with a non-zero code and a friendly message (e.g. `agents foo`, `publishers list-tools`).

## Process

### Mapping `/discovery-catalog ...` requests to invocations

When the user types a slash-style invocation like `/discovery-catalog publishers`, run the dispatcher with the matching arguments:

| User says | Run |
|---|---|
| `/discovery-catalog publishers` | `pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 publishers` |
| `/discovery-catalog agents` | `... discovery-catalog.ps1 agents` |
| `/discovery-catalog agents list-tools` | `... discovery-catalog.ps1 agents list-tools` |
| `/discovery-catalog starter-kits` | `... discovery-catalog.ps1 starter-kits` |
| `/discovery-catalog <agent-name> describe` | `... discovery-catalog.ps1 <agent-name> describe` |
| `/discovery-catalog <starterkit-name> describe` | `... discovery-catalog.ps1 <starterkit-name> describe` |
| `/discovery-catalog <agent-name> list-tools` | `... discovery-catalog.ps1 <agent-name> list-tools` |

Use `-Format Table` for all catalog responses. Only add `-Format Markdown` if the user explicitly asks for a paste-ready markdown table.
When the dispatcher output is long, gather the full result before replying; never mention internal transport details, truncation, temp files, or resource files to the user.
Always return the complete table for the requested command; do not shorten it to a partial list or a narrative summary.
In chat responses, present tabular results as Markdown tables for readability, while keeping the count anchor line (`*_COUNT=`) above the table.

### How the dispatcher works (internal — for skill maintainers)

1. Resolve repo root via `git rev-parse --show-toplevel`.
2. Walk `agents/` and/or `starter-kits/` one level deep, skipping `tmp/`.
3. Inclusion: agent folders need `agent.yaml`; starter-kit folders need `kit.json`.
4. For each entry, parse the appropriate metadata file:
   - Agent: `metadata.yaml` for `name`, `version`, `description`, `tags`, plus the nested `publisher.name` and `publisher.party`.
   - Starter kit: `kit.json` for `name`, `version`, `description`, `category`, `party`, `author.name`, plus top-level `agentRefs`; treat the `role: primary` entry as the launch agent.
   - Tool (when `agents list-tools`): `tool.yaml` for `name`; folder name as fallback.
5. Apply filters: `-Publisher`, `-Tag`, `-WithToolsOnly`, `-WithoutToolsOnly`.
6. Sort by name (and publisher where applicable).
7. Render in the requested format.

The first line of `Table` and `Markdown` output is a deterministic count anchor (`AGENT_COUNT=`, `PUBLISHER_COUNT=`, `STARTER_KIT_COUNT=`) so callers can grep for it.

## Output Format

### `discovery-catalog publishers`

```
PUBLISHER_COUNT=2

Publisher              Party AgentCount StarterKits
---------              ----- ---------- -----------
Contoso Legal Tech     3p             1           0
Microsoft              1p            41           2
```

### `discovery-catalog agents`

```
AGENT_COUNT=41

Agent                 Publisher  Party
----                 ---------  -----
aizynthfinder        Microsoft  1p
online-researcher    Microsoft  1p
...
```

### `discovery-catalog agents list-tools`

```
AGENT_COUNT=41

Agent                  Publisher  Tools
----                  ---------  -----
aizynthfinder         Microsoft  tools/aizynthfinder
bookshelf-researcher  Microsoft  (no tools)
...
```

### `discovery-catalog starter-kits`

```
STARTER_KIT_COUNT=2

Starter-Kit                  Publisher  Category
----                         ---------  --------
drug-discovery               Microsoft  Chemistry
protein-structure-analysis   Microsoft  Biology
```

### `discovery-catalog <agent-name> describe`

```
Name           Publisher  Version HasTool Description
----           ---------  ------- ------- -----------
aizynthfinder  Microsoft  1.0.0      True Expert agent for retrosynthetic route planning using AiZynthFinder...
```

### `discovery-catalog <starterkit-name> describe`

```
Name            Publisher  Version Category  AgentCount Description
----            ---------  ------- --------  ---------- -----------
drug-discovery  Microsoft  1.0.0   Chemistry          5 Accelerate small-molecule drug discovery...
```

### `discovery-catalog <agent-name> list-tools`

```
Agent          Publisher  Version ToolCount Tools         Description
-----          ---------  ------- --------- -----         -----------
aizynthfinder  Microsoft  1.0.0           1 aizynthFinder Expert agent for retrosynthetic route planning using AiZynthFinder...
```

## Examples

### Example 1: List publishers

**User**: *"Who publishes agents in this repo?"*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 publishers
```

### Example 2: List all agents

**User**: *"What agents do we have?"*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 agents
```

### Example 3: List agents with their tools

**User**: *"Show me each agent and the tools it ships."*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 agents list-tools
```

### Example 4: List starter kits

**User**: *"What starter kits are available?"*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 starter-kits
```

### Example 5: Describe a specific item

**User**: *"Describe the `drug-discovery` starter kit"*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 drug-discovery describe
```

**User**: *"Describe `aizynthfinder`"*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 aizynthfinder describe
```

### Example 6: Show tools for one agent

**User**: *"List tools for `aizynthfinder`"*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 aizynthfinder list-tools
```

### Example 7: Filtered queries

**User**: *"Which agents have a `retrosynthesis` tag?"*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 agents -Tag retrosynthesis
```

**User**: *"Which agents don't have a tool yet?"*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 agents -WithoutToolsOnly
```

**User**: *"Which agents are published by Microsoft?"*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 agents -Publisher Microsoft
```

### Example 8: Markdown for a doc

**User**: *"Give me a markdown table of all starter kits I can paste into a README."*

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .github/skills/discovery-catalog/scripts/discovery-catalog.ps1 starter-kits -Format Markdown
```

## Guidelines

- **Read-only**: never writes to the repo or to Azure. Safe to run repeatedly.
- **Display name is the folder name** — agents and starter kits are shown by their flat-layout folder name; publisher is rendered as a separate column populated from `metadata.yaml`/`kit.json`.
- **Folder names are globally unique** in the flat layout, so `<agent-name>` alone is enough to disambiguate.
- **Command examples use PowerShell 7+ (`pwsh`)** and work on Windows, macOS, and Linux when PowerShell is installed.
- **Always include the count anchor** (`PUBLISHER_COUNT=`, `AGENT_COUNT=`, `STARTER_KIT_COUNT=`) in `Table`/`Markdown` output so downstream automation has a deterministic anchor.
- **Prefer tabular output** for every catalog query; do not use `Json` or `Plain` for normal discovery responses.
- **Return the full table** for the requested command; never replace rows with a summary, excerpt, or placeholder text.
- **Render user-facing tables in Markdown** so columns remain aligned in chat.
- **Never narrate internal handling** such as reading from a resource file or hitting a terminal output limit.
- **Don't crash on missing metadata** — entries with missing `metadata.yaml` or unparseable `kit.json` are silently skipped (kits) or shown with empty fields (agents). Missing `publisher.name` is rendered as `(unspecified)`.
- **Don't list `agents/tmp/`** — it's the scratch tree used by other skills (`discovery-services-agent-deployer`) and is gitignored.
- **PS 7+ recommended** so `Format-Table -AutoSize -Wrap` renders long descriptions cleanly. The script works in Windows PowerShell 5.1 too but wrapping is uglier.
- **Invalid subcommands exit with non-zero code** and a friendly message — the dispatcher rejects e.g. `agents foo` or `publishers list-tools`.
