# Microsoft Discovery: Quick Start Guide 🧪

> **Your first 15 minutes with Microsoft Discovery** — zero cloud, zero IT ticket, all hands-on.

---

## What is Microsoft Discovery?

Microsoft Discovery is the AI-augmented science and engineering platform, offered as a **Microsoft Discovery app** (the local-first Windows client this Quick Start covers) and **Microsoft Discovery services** (cloud-hosted, [documented on Microsoft Learn](https://learn.microsoft.com/en-us/azure/microsoft-discovery/)). Install the app on your laptop and you immediately have:

- 📚 **A searchable knowledge base** of your own papers, docs, and code (Bookshelf)
- 🔧 **Curated scientific tools** ready to deploy to GitHub Copilot, Claude, or Cursor (Tool Catalog)
- 📋 **A task graph** that captures the real, hierarchical shape of research work (Tasks)
- 🤖 **Autonomous agents** that run multi-step research in the background (Discovery Engines)
- 📓 **A lab notebook** for collecting, organizing, and publishing findings (Notebook)
- ⌨️ **A CLI** that exposes every capability for scripts and automation (`dx`)

You don't need an Azure subscription. You don't need cloud credentials. Everything runs on your machine.

---

## The 5-Minute Concept Map

Before you click anything, here's how Microsoft Discovery is organized:

```
📁 Your workspace folder (any folder you choose)
 └── 📂 .discovery/        ← all Microsoft Discovery state lives here, version-controllable
      ├── config.json       ← engines, models, providers
      ├── bookshelves/      ← indexed knowledge
      ├── tasks/            ← task graph (DAG)
      ├── notebooks/        ← findings and write-ups
      └── engines/          ← Discovery Engine state
```

| Concept | Real-World Analogy | What It Does |
| --- | --- | --- |
| **Workspace** | Your lab notebook drawer | Any folder on disk. Microsoft Discovery keeps its state in `.discovery/` inside it. |
| **Lab Notebooks** 📓 | Your bench journal | Where you collect findings, decisions, and hypotheses, and publish them as wiki pages, briefs, or papers. |
| **Bookshelf** 📚 | A smart filing cabinet that reads every paper inside it | Ingests text-based formats such as PDFs, Markdown, Office formats, and code. Indexes it for semantic, keyword, and graph search. |
| **Tool Catalog** 🔧 | A plug-in panel of scientific instruments | Curated MCP servers (PubMed, RCSB PDB, arXiv, etc.) you can deploy to your AI assistants in one click. |
| **Tasks** 📋 | The whiteboard plan for the project | A directed-acyclic graph of work items with explicit dependencies, status, and ownership. Not a flat to-do list. |
| **Purpose** 💫| A grading rubric | A structured statement of intent that is used to capture why a Task exists and to measure how closely a Task's output fulfils that intent. |
| **Engines** 🛞 | A tireless junior researcher | A long-running autonomous agent that uses your bookshelves, agents, and tools to make multi-step progress. |
| **Agents**  🤖 | A specialist hired for a specific job | A purpose-built composition of capabilities packaged as a reusable .agent.md file which can invoked in Discovery. |
| **Dependencies** ✅| A pre-flight checklist | The SDK layer that manages the external runtime components that Discovery needs to function. |
| **`dx` CLI** ⌨️ | The keyboard shortcut to everything | The same SDK as the extension, exposed as a command-line tool for scripts and automation. |

---

## Step 0: Install Microsoft Discovery 💾

Download the installer from the latest release and run it. That's it.

👉 **[Download the latest Microsoft Discovery installer](https://github.com/microsoft/discovery/releases/latest)** — pick the `DiscoveryExpressSetup-x.y.z.exe` asset.

> ⚠️ **Prerequisites.** Windows and an active **GitHub Copilot subscription**. Microsoft Discovery is a self-contained Windows app — VS Code is *optional* and only needed if you want the VS Code integration surface. See [install.md](install.md) for the full prerequisite list and verification steps.

After installation, open VS Code. You'll see the **Microsoft Discovery** icon in the Activity Bar (the vertical strip on the left). If it's there, you're done.

> 💡 **Try this now.** Open VS Code and confirm you see the Microsoft Discovery icon in the Activity Bar. Click it.

---

## Step 1: Tour the Sidebar 🗂️

Click the Microsoft Discovery icon. The sidebar opens with a tree view. Here's what you'll see:

```
◆ MICROSOFT DISCOVERY
 ├── 📁 Workspace        ← files in your project, with Microsoft Discovery-aware actions
 ├── 📓 Notebooks         ← Jupyter, Wiki, and Brief notebooks
 ├── 📚 Bookshelf         ← your indexed knowledge bases
 ├── 🔧 Tool Catalog      ← MCP servers and agent plugins
 ├── 📋 Tasks             ← your task graph
 └── 🤖 Engines           ← configured Discovery Engines
```

A few things to know:

- **Checkboxes** next to a Bookshelf or Tool Catalog source toggle whether it's exposed to GitHub Copilot. Tick the box, and Copilot can use it as a tool. Untick it, and Copilot can't.
- **Health dots** (green / yellow / red) show whether a provider or source is reachable.
- **Right-click any item** to open the context menus and see what you can do with it.

---

## Step 2: Create a Workspace

1. In the **Workspace** panel, click **Create a new Workspace**.
2. Select any folder to store your Discovery Express assets.
3. Wait for all dependencies to finish installing; each dependency will show a progress bar as it loads.

---

## Step 3: Build Your First Bookshelf 📚

A Bookshelf is a local, searchable index of your documents.

### Create a Bookshelf

1. In the **Bookshelf** panel, click the **+** button.
2. Name it something memorable, like `MyResearchPapers`.
3. Choose a provider if prompted. The provider is the algorithm used to read, index, and search your documents. The default is fine for now.

### Ingest some documents

1. Right-click the new shelf and choose **Ingest Documents**.
2. Pick two or more individual files or a folder of text-based files such as PDFs, Markdown, Office formats, or code.
3. Wait. Indexing happens in the background; the shelf shows progress as it goes.

> 🔖 **Remember.** Microsoft Discovery ships with a **bundled local embedding model** (`all-MiniLM-L6-v2` ONNX). Semantic search works **immediately, offline, with no API key**. If you have an Azure OpenAI key configured, Microsoft Discovery uses that instead for higher quality — but you don't have to.

### Confirm it worked

When ingestion finishes, the shelf shows a document count and a green health dot. You now have a domain-aware index of your own content.

> 💡 **Try this now.** Create a shelf called `QuickStart` and ingest a folder of papers or notes you actually use. Even a few PDFs is enough to test with.

---

## Step 4: Ask Copilot About Your Stuff 💬

Now let's make Copilot use the shelf you just built.

1. **Tick the checkbox** next to your new shelf in the Bookshelf panel. That exposes it to GitHub Copilot as a tool.
2. **Open Copilot Chat** (`Ctrl+Alt+I` on Windows, or click the chat icon).
3. **Ask a domain question** that depends on the documents you ingested:

```
What are the key findings on protein folding in my Quick Start shelf?
```

Copilot will pick up your bookshelf as a tool, search it, and respond **with citations** that point back into your documents.

> 💡 **Try this now.** Tick your shelf's checkbox and ask Copilot a question that only your ingested papers can answer. The citations are the proof.

---

## Step 5: Pull in Scientific Tools 🔧

Microsoft Discovery's **Agent Plugin Marketplace** has 8 curated, free MCP servers across 3 scientific disciplines, all backed by major scientific organizations.

| Category | Plugins |
| --- | --- |
| **Biomedical & Life Sciences** 🧬 | BioMCP (PubMed + clinical trials), RCSB PDB (protein structures), UniProt (protein sequences), NCBI Entrez (gene / protein / nucleotide databases) |
| **Physical Sciences & Engineering** ⚛️ | NASA PDS (planetary data), OPTIMADE (crystal structures, materials science) |
| **Scientific Literature & Search** 📄 | arXiv (preprints), bioRxiv / medRxiv (biology and medical preprints) |

### Add the marketplace

The Agent Plugin Marketplace is a Git repository of plugin manifests. Add its URL to your VS Code user settings:

```jsonc
// settings.json
"chat.plugins.marketplaces": [
  // Agent Plugin Marketplace URL
]
```

### Enable a plugin

Open the **Agent Plugins** panel in VS Code, find a plugin, and toggle it on. VS Code's native plugin host handles the rest — start, stop, reconnect, all automatic. The plugin is immediately available in Copilot Chat.

> ⚠️ **Watch out.** Most of these MCP servers call live external APIs, so they need internet access at query time even though Microsoft Discovery itself runs locally.
>
> 💡 **Try this now.** Enable **arXiv** and ask Copilot Chat: `Find recent arXiv papers on diffusion models for protein design.`

---

## Step 6: Plan Work with Tasks 📋

Tasks in Microsoft Discovery are not a flat checklist. They're a **directed-acyclic graph** with explicit dependencies, a real status state machine, and queries like "what's ready to work on?" and "what's blocked?".

### The status state machine (in plain English)

| Status | Meaning |
| --- | --- |
| `new` | Created, not started |
| `executing` | Actively in progress |
| `executionDone` | Work is finished, awaiting verification |
| `complete` | Verified done |
| `onHold` | Paused intentionally |
| `failed` | Tried, didn't work |
| `incomplete` | Started but won't be finished |
| `stale` | Untouched too long |
| `flaggedHuman` / `flaggedAi` | Needs attention from a person or an AI |
| `removed` | Soft-deleted |

> 🔖 **Remember.** Status names are exact. `done`, `in-progress`, `closed`, and `pending` are **not** valid — the system rejects them. Use the values above.

### Create your first task graph

Open Copilot Chat and ask it to break a real research plan down for you:

```
Use the tasks tool to plan a 5-step literature review on solid-state battery cathodes.
Create a parent task and 5 dependent sub-tasks.
```

Copilot will create the parent task, the children, and the dependency edges. Open the **Tasks** panel and watch them appear.

### Find what's ready

Ask Copilot:

```
What tasks are ready to work on right now?
```

A task is **ready** when all its dependencies are `complete` or `executionDone`. **Blocked** is the opposite. These are first-class queries in the Tasks tool — not something you have to compute by hand.

> 💡 **Try this now.** Ask Copilot to plan a 3-step task graph for a real piece of work you have this week, then ask it which task is ready first.

---

## Step 7: Start a Discovery Engine 🤖

A **Discovery Engine** is a long-running agent that uses your Microsoft Discovery tools to make multi-step progress. Engines are great for jobs you'd hand to a careful intern — "go scan these papers and summarize anything new about X," "watch this folder and triage incoming results."

### Autonomy levels

| Level | What it means |
| --- | --- |
| **Full** | The engine uses any of its allowed tools without asking. |
| **Supervised** | The engine proposes each tool call and waits for your approval. **This is the right setting for your first run.** |
| **Locked** | The engine can only use a strict whitelist of tools. |

### Configure an engine

Engines are defined in `.discovery/config.json` under `cognition.engines`. The two production-ready adapters are **`copilot-cli`** (drives GitHub Copilot CLI) and **`clio`** (CLIO's reasoning engine).

```jsonc
{
  "cognition": {
    "engines": [
      {
        "definitionId": "research-sweep",
        "displayName": "Research Sweep",
        "adapterKind": "copilot-cli",
        "systemPrompt": "Search bookshelves, synthesize findings, produce a summary.",
        "policy": { "level": "Supervised" }
      }
    ]
  }
}
```

### Start it

Two equivalent ways:

- **Command Palette** (`Ctrl+Shift+P`) → `Microsoft Discovery: Start Engine` → pick `research-sweep`.
- **Copilot Chat**: `Start the research-sweep engine and analyze my Quick Start shelf.`

In Supervised mode, a dialog appears for each proposed action; you approve or deny it. You can pause, resume, or stop the engine from the **Engines** panel at any time.

> ⚠️ **Watch out.** Don't run a brand-new engine in `Full` mode against tools that mutate external systems. Use `Supervised` until you trust both the prompt and the tools.
>
> 💡 **Try this now.** Add the snippet above to your `.discovery/config.json`, start the engine in Supervised mode, and approve a few actions to see how it works.

---

## Step 8: Capture Findings in a Notebook 📓

A Notebook is where research **content** lives — findings, decisions, hypotheses, and write-ups. Microsoft Discovery supports three formats; you pick the one that fits how you work.

| Format | When to use it | What it looks like |
| --- | --- | --- |
| **Jupyter** | Personal lab journal; mixing notes and executable cells; chronological log | A single notebook file in the VS Code notebook editor. Drag content from chat into typed cells (Finding, Decision, Hypothesis…). |
| **Wiki** | Team-shared project knowledge; themed pages anyone can browse | A folder of `.md` files (`decisions.md`, `findings.md`, `notes.md`) you edit directly. |
| **Brief** | Executive summary that auto-updates as work progresses | A single `brief.md` the system proposes updates to; you accept or reject. |

### Create a notebook

- **In Copilot Chat**: `Create a wiki notebook called Catalyst Study.`
- **In the sidebar**: open the **Notebooks** panel, click **+**, choose a format, name it.

### Add content to it

You have several options, all equivalent:

- Type directly into the file (Wiki / Brief) or notebook editor (Jupyter).
- Pin a result from a Bookshelf search.
- Paste into Copilot Chat: `Save this to my notebook: [paste your text]`.
- Drop files into the notebook's sources folder; they're picked up on the next session.

### Publish

Any notebook can be rendered to a shareable format:

```
Render my Catalyst Study notebook as LaTeX.
```

Wiki pages, LaTeX, and PowerPoint outlines are supported today.

> 🔖 **Remember.** Everything in `.discovery/` is plain files on disk. You can `git init` your workspace folder and version-control your bookshelves, tasks, and notebooks just like code.
>
> 💡 **Try this now.** Ask Copilot Chat to create a Wiki notebook for the project you're working on, then save your last interesting Bookshelf answer to it.

---

## Step 9: Drive Everything from the dx CLI (Optional) ⌨️

If you'd rather type than click — or you're scripting a pipeline — the `dx` CLI exposes the same SDK as the extension.

### Bootstrap a workspace

```powershell
dx init --workspace C:\work\my-project
dx doctor --workspace C:\work\my-project
```

### Bookshelf from the CLI

```powershell
dx bookshelf create papers --workspace C:\work\my-project
dx bookshelf ingest <shelf-id> C:\papers --recursive --workspace C:\work\my-project
dx bookshelf search <shelf-id> "battery electrolyte stability" --workspace C:\work\my-project
dx bookshelf ask "What are the main failure modes?" --shelf <shelf-id> --sources --workspace C:\work\my-project
```

### Tasks, Tool Catalog, and Engines

```powershell
dx task create "Review new catalyst results" --priority 2 --workspace C:\work\my-project
dx task graph --workspace C:\work\my-project --output json

dx catalog list --workspace C:\work\my-project
dx catalog add-mcp "Microsoft Learn" https://example.com/mcp --transport http --workspace C:\work\my-project

dx engine list-definitions --workspace C:\work\my-project
dx engine routing-snapshot --workspace C:\work\my-project
```

### Configure your model

```powershell
dx workspace config llm show --workspace C:\work\my-project
dx workspace config llm test --workspace C:\work\my-project
```

> 💡 **Try this now.** Run `dx doctor --workspace .` from your project folder and read the output. It tells you exactly which capabilities are ready to go.

---

## What Just Happened? 🎉

In about 15 minutes you've:

- ✅ Installed Microsoft Discovery on your laptop with no Azure account, no cloud credentials, and no IT ticket
- ✅ Built a domain-aware Bookshelf and queried it from Copilot with citations
- ✅ Pulled in curated scientific MCP servers from the Agent Plugin Marketplace
- ✅ Built a real task graph with dependencies and asked Copilot what's ready to work on
- ✅ Started a Supervised Discovery Engine and approved its first actions
- ✅ Created a Notebook to capture findings and learned how to publish it
- ✅ Discovered that everything you just did is also accessible from the `dx` CLI

---

## Key Takeaways

| # | Lesson |
| --- | --- |
| 1 | **Local-first.** Your data, your indices, your tasks, your notebooks — all on your machine, all version-controllable. |
| 2 | **Three surfaces, one SDK.** The VS Code extension, the `dx` CLI, and your AI assistant all talk to the same engine. Switch surfaces freely. |
| 3 | **Bookshelf + Copilot is the wow moment.** Domain-aware AI for your own documents in seconds, with no API keys. |
| 4 | **Tasks are a graph, not a list.** Dependencies are first-class, status is a state machine, and "ready" is a query. |
| 5 | **Supervised first.** Run new engines in Supervised mode until you trust both the prompt and the tools they touch. |

---

## Next Steps 🚀

You've got the basics. Here's where to go deeper.

### Customize a Bookshelf provider

Each shelf has exactly one active provider. The default works out of the box, but you can switch a shelf to a different provider (e.g. Azure AI Search) for higher-quality retrieval over very large corpora.

### Build a multi-step Task graph

Hand-craft a task DAG with real dependencies for a piece of work you actually own this week. Use `dx task dep add` to wire the edges, then ask Copilot which task is ready first.

### Author your own Discovery Engine

Define a custom engine in `.discovery/config.json` with your own system prompt, autonomy policy, and per-tool rules.

### Share what you build

Share your workflows, prompts, and plugins in [Discussions → Show and tell](https://github.com/microsoft/discovery/discussions/categories/show-and-tell). If you'd like to land an agent or starter kit in this catalog, see [`CONTRIBUTING.md`](../../CONTRIBUTING.md) and the authoring guides under [`docs/authoring-guides/`](../authoring-guides/).

### Pair with Microsoft Discovery services for team scale

When your work outgrows a single laptop, your bookshelves, tools, and workflows carry forward into [Microsoft Discovery services](https://learn.microsoft.com/en-us/azure/microsoft-discovery/) — the cloud-hosted, enterprise-scale platform — without starting over.

---

## Glossary

| Term | Definition |
| --- | --- |
| **Bookshelf** | A local, multi-strategy (vector / keyword / graph) index of documents you've ingested. |
| **Provider** | The backend a Bookshelf uses for indexing and search. Each shelf has exactly one. |
| **MCP** | **Model Context Protocol** — the standard interface AI assistants use to call external tools. Microsoft Discovery exposes its capabilities as MCP tools. |
| **Agent Plugin** | A VS Code-standard manifest (`agent-plugin.json`) that wires up an MCP server as a Copilot tool. The marketplace is a Git repo of these. |
| **RAG** | **Retrieval-Augmented Generation** — the pattern where an AI searches a knowledge base, then uses what it finds to answer. Bookshelf is RAG for your own docs. |
| **Embedding** | A numeric fingerprint of text used for semantic search. Microsoft Discovery uses a bundled local ONNX model by default. |
| **ONNX** | An open format for ML models. The bundled embedding model runs locally as ONNX so semantic search works offline. |
| **Engine / Adapter** | A Discovery Engine is the agent; the **adapter** is the runtime it talks to. Production adapters today are `copilot-cli` and `clio`. |
| **Autonomy policy** | The rule set that controls what tools an engine can use — `Full`, `Supervised`, or `Locked`. |
| **DAG** | **Directed Acyclic Graph** — the shape of the Tasks tree. Edges are explicit dependencies, not implicit ordering. |
| **`.discovery/`** | The folder inside your workspace where Microsoft Discovery stores all its state. Plain files; commit it to git if you want. |
| **`dx`** | The Microsoft Discovery CLI. Same SDK as the app, exposed as a command-line tool. |

---

## Troubleshooting

| Problem | What to try |
| --- | --- |
| **No Microsoft Discovery icon in the Activity Bar** | The extension didn't activate. Restart VS Code. If still missing, reinstall from the installer. |
| **Bookshelf indexing stays at "Processing"** | Large folders take a few minutes. If it's stuck longer than that, right-click the shelf and choose **Cancel Indexing**, then re-ingest a smaller subset to confirm the provider is healthy. |
| **Copilot doesn't seem to use my Bookshelf** | Check the **checkbox** next to the shelf is ticked — that's what exposes it to Copilot. Reload the VS Code window if you just ticked it. |
| **An Agent Plugin isn't showing up** | Confirm the marketplace URL is in `chat.plugins.marketplaces` in your **user** settings (not workspace settings). Reload VS Code. |
| **An engine won't start** | Open the **Engines** panel, hover the entry for an error tooltip, then run `dx engine routing-snapshot` from a terminal to see what tools are wired up. |
| **`dx` says "no workspace"** | Either pass `--workspace <path>` explicitly, or run `dx init --workspace <path>` once to create the `.discovery/` folder. |
| **LLM-backed commands return warnings instead of answers** | No model route is configured. Run `dx workspace config llm show` to inspect, and `dx workspace config llm set-azure-openai ...` to point at your endpoint. Local embedding still works without this. |
| **Need a deeper diagnostic** | `dx doctor --workspace .` walks every dependency, model route, and provider and tells you exactly what's broken. |

---

<div align="center">

**Microsoft Discovery** — _AI-augmented science and engineering._

</div>
