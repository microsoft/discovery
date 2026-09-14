# Causaly Agentic Research

Biomedical and life-sciences research agent powered by the Causaly Agentic Research platform. It delegates a natural-language biomedical question to Causaly, which searches, reads, and cross-checks evidence across a curated knowledge graph and the primary literature, then returns a narrative answer with per-claim inline citations, a continuable research thread, and — on request — a structured source list. Prefer over the default agent for biomedical interpretation.

## Contents

| File | Purpose |
|---|---|
| `causaly-agentic-research.agent.md` | The agent. Discovery defines an agent as "a reusable `.agent.md` file." |
| `.vscode/mcp.json` | MCP server registration. Copy into your workspace. |

## Prerequisites

- **Windows**, plus an active **GitHub Copilot subscription** — the Discovery app's own requirements.
- **VS Code.** The Discovery app treats VS Code as optional, but this package does not: `.vscode/mcp.json` and `.github/agents/` are both VS Code mechanisms. A recent version is needed for `"type": "http"` MCP servers and for MCP OAuth.
- A **Causaly account with Agentic Research enabled**. The server acts on your behalf with your own entitlements.

## Setup

### 1. Register the MCP server

Register the MCP server by dropping `.vscode/mcp.json` into your workspace:

```json
{
  "servers": {
    "causaly-ar-mcp-server": {
      "url": "https://med.causaly.com/mcp/v1/agentic-research",
      "type": "http"
    }
  }
}
```
No keys or secrets go in the configuration. Causaly's server is a standard remote MCP server over Streamable HTTP, authenticated with OAuth 2.1 and supporting dynamic client registration — so on first use the client opens Causaly's sign-in page, completes the flow for you, and refreshes quietly from then on.

The `tools:` frontmatter in `causaly-agentic-research.agent.md` lists all four Causaly tools explicitly as `causaly-ar-mcp-server/<tool>`. That prefix must match the name you register the server under — `causaly-ar-mcp-server` above. If you register it as something else, update all four entries, or the agent loads without the Causaly tools and silently falls back to answering from model knowledge — the exact failure the prompt is written to prevent.

### 2. Install the agent

Put `causaly-agentic-research.agent.md` in your workspace's **`.github/agents/`** folder — the default location VS Code scans for custom agents. (`.claude/agents/` also works, and `chat.agentFilesLocations` can add others.) Then select it as the active agent, and verify the four Causaly tools are listed as available before your first real question.

### 3. Smoke-test it

Ask something small and unambiguously biomedical:

```
What is the evidence linking IL-23 inhibition to remission in Crohn's disease?
```

You should see it call `causaly_research`, then poll `causaly_wait_for_research` several times — that polling is correct behaviour, not a hang. A five-to-ten-minute run is normal. What comes back should be Causaly's prose verbatim with inline numbered citation links — and **no** `**Sources**` list, because that prompt does not ask for one. Add "and list the references" to see the block appear.

Three things to check on that first run, because they are the failure modes worth catching early:

- **Citations survived.** Inline numbers are present and each links out.
- **Nothing was paraphrased.** If the answer reads like a tidy summary rather than Causaly's own text, the agent file is not being applied — check it is the active agent.
- **Causaly actually answered it.** Confirm `causaly_research` and `causaly_wait_for_research` appear in the tool calls.

## Known limitations

- **Requires a Causaly account with Agentic Research**, plus Windows and a GitHub Copilot subscription for the Discovery app itself.
- **Latency is inherent.** Every MCP run uses extended reasoning; expect minutes and many poll calls.
- **One question at a time per chat.** Parallel questions need separate chats.

## Support

Causaly platform or connection problems: <support@causaly.com>.
