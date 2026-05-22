# Microsoft Discovery

Welcome to the **Microsoft Discovery community** — the public home for the Discovery platform, where users, partners, and the product team build together. Share what you've built, ask questions, file bugs, suggest ideas, and see what other Discovery users are doing across disciplines.

> **Microsoft Discovery is an extensible platform that brings together agentic orchestration, advanced reasoning, a graph-based knowledge foundation, and high-performance computing for scientific research and R&D workflows.**

Microsoft Discovery is offered in two complementary experiences that share the same core concepts — a **Bookshelf** of indexed knowledge, a **Tasks** graph, a **Discovery Engine** for autonomous multi-step work, and a **Tool Catalog** of MCP-backed scientific tools:

| Experience | What it is | Where to start |
| --- | --- | --- |
| 🖥️ **Microsoft Discovery app** | A local-first Windows client for individual evaluation on a laptop. **Distributed from this repository.** | [`docs/apps/`](docs/apps/) — install, quickstart, feedback |
| ☁️ **Microsoft Discovery services** | The cloud-hosted, team-scale experience on Azure. | [Microsoft Learn](https://learn.microsoft.com/en-us/azure/microsoft-discovery/) — full reference |

In addition, this repository hosts the **public Discovery Catalog** — the canonical metadata catalog of AI research **agents** and **starter kits** contributed by Microsoft and ecosystem partners. Agent code, container images, and model weights live in each contributor's own infrastructure; the metadata and documentation that describe them live here, where they are PR-reviewed, schema-validated, and surfaced to every Discovery user.

---

## 🧭 Core concepts

The canonical conceptual reference for both the app and the services is [Microsoft Discovery on Microsoft Learn](https://learn.microsoft.com/en-us/azure/microsoft-discovery/). The starting points most users want:

- [Discovery Agent concepts](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-discovery-agent) — what an agent is and how it's invoked
- [Discovery Engine overview](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-discovery-engine) — the cognition layer
- [Bookshelf and Knowledge Bases](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-bookshelf-knowledge-bases) — how indexing and retrieval work
- [Tasks and investigations](https://learn.microsoft.com/en-us/azure/microsoft-discovery/concept-tasks-investigations) — the task-graph model

For an app-specific 15-minute hands-on tour, see [`docs/apps/quickstart.md`](docs/apps/quickstart.md).

---

## 📦 What's in this repository

| Surface | What it is | Best for |
| --- | --- | --- |
| 📥 **[Releases](https://github.com/microsoft/discovery/releases)** | Signed Windows installers (`DiscoveryExpressSetup-x.y.z.exe`) and release notes for the Discovery app. | Downloading the latest build of the app. |
| 🤖 **`agents/`** | Catalog of AI research agents (1P and 3P) surfaced in Discovery. Each entry contains a `metadata.yaml`, `agent.yaml`, `README.md`, and optional `tools/`. | Browsing what's available, or contributing a new agent. |
| 🧰 **`starter-kits/`** | Catalog of starter kits — `kit.json` manifests that bundle one or more catalog agents into a launchable scenario. | Browsing pre-built workflows, or publishing a new kit. |
| 💬 **[Discussions](https://github.com/microsoft/discovery/discussions)** | Q&A, Ideas, Bugs, and Show-and-tell — the single place for everything from "how do I…?" to bug reports, ideas, and sharing what you've built. | Asking questions, suggesting ideas, sharing what you've built, and reporting bugs. |
| 🧪 **[`.github/skills/`](.github/skills/)** | Three Copilot skills auto-discovered by Copilot CLI and VS Code Copilot Chat — for browsing the catalog and deploying agents / starter kits to **Microsoft Discovery services** (cloud, via Microsoft Foundry). Not used by the local Discovery app today. | Researchers and developers integrating the catalog into a Microsoft Foundry workflow. |

---

## 🗂️ Repository layout

```text
discovery/
├── agents/
│   └── <agent-name>/                         ← flat catalog: one folder per agent
│       ├── metadata.yaml                     ← Discovery catalog contract (required)
│       ├── agent.yaml                        ← Prompt-agent definition (required)
│       ├── README.md                         ← Agent documentation (required)
│       └── tools/<tool-name>/                ← Discovery-managed tools (optional)
│           ├── tool.yaml
│           └── Dockerfile
├── starter-kits/
│   └── <kit-name>/                           ← flat catalog: one folder per kit
│       └── kit.json                          ← Starter-kit manifest (required, the only file allowed in the folder)
├── .auto-registry/                           ← Auto-generated; do not edit
│   ├── agent-registry.json
│   └── starter-kit-registry.json
├── docs/
│   ├── apps/                                 ← End-user docs for the Discovery app
│   │   ├── install.md
│   │   ├── quickstart.md
│   │   └── feedback.md
│   ├── services/                             ← Pointer to Microsoft Learn (services live there)
│   ├── authoring-guides/                     ← How to author and submit catalog content
│   │   ├── agent-authoring-guide.md
│   │   └── starter-kit-authoring-guide.md
│   └── schemas/                              ← Canonical JSON schemas (*-schema.json)
├── .github/
│   ├── skills/                               ← Copilot skills (auto-discovered)
│   │   ├── discovery-catalog/                          ← Read-only catalog inventory
│   │   ├── discovery-services-agent-deployer/          ← Agent deployment to Microsoft Foundry
│   │   └── discovery-services-starter-kit-deployer/    ← Starter-kit deployment to Microsoft Foundry
│   ├── DISCUSSION_TEMPLATE/                  ← Templates for Bugs / Ideas / Q&A / Show-and-tell
│   ├── workflows/                            ← Automated PR validation and registry pipelines
│   ├── scripts/                              ← Python validation and registry-builder scripts
│   ├── CODEOWNERS                            ← Maintainer assignments
│   └── pull_request_template.md
└── .vscode/                                  ← Editor settings: wires JSON Schemas to YAML/JSON files; recommends Copilot, PowerShell, Python, YAML, and markdownlint extensions
```

> The catalog uses a **flat layout** — there is no Microsoft-versus-partner folder split. The optional `party` field inside `metadata.yaml` and `kit.json` (`1p` for Microsoft-authored, `3p` for partner-contributed) drives PR labels and surfacing; it is not encoded in the folder path.

---

## 🚀 Get started

### Install and use the Discovery app

The Microsoft Discovery app is a **self-contained Windows application** — no SDK, no cloud setup, no IT ticket. Download the signed installer and double-click.

1. **Check prerequisites** and download the installer — see [`docs/apps/install.md`](docs/apps/install.md).
2. **Run it.** The app launches as a standard Windows application.
3. **Follow the 15-minute tour** — [`docs/apps/quickstart.md`](docs/apps/quickstart.md) walks you through building your first Bookshelf, creating a Task graph, and running a Discovery Engine.
4. **Have feedback?** See [`docs/apps/feedback.md`](docs/apps/feedback.md).

### Use Microsoft Discovery services (cloud)

Microsoft Discovery services run on Azure and are documented separately at [learn.microsoft.com/azure/microsoft-discovery](https://learn.microsoft.com/en-us/azure/microsoft-discovery/). For browsing and deploying catalog content from this repo *into* a Microsoft Foundry project, use the Copilot skills below.

### Browse the catalog

- **Agents:** open the `agents/` directory — each folder is one agent with its own `README.md`.
- **Starter kits:** open the `starter-kits/` directory — each folder contains a single `kit.json` describing the bundled agents, sample prompts, and risk profile.
- **Programmatic access:** the same content is exposed as a single aggregated JSON in [`.auto-registry/agent-registry.json`](.auto-registry/agent-registry.json) and [`.auto-registry/starter-kit-registry.json`](.auto-registry/starter-kit-registry.json), regenerated automatically on every merge.

---

## 🛠️ Copilot skills

> **Scope:** these skills target **Microsoft Discovery services** (the cloud-hosted experience on Microsoft Foundry). They are not used by, and have no effect on, the local **Microsoft Discovery app** today. If you're evaluating the app on your laptop, you can safely skip this section.

This repo ships three GitHub Copilot skills under [`.github/skills/`](.github/skills/). They are **auto-discovered by both Copilot CLI and VS Code GitHub Copilot Chat** — no `/plugin install`, no marketplace step, no per-machine setup. Just open the repo.

| Skill | Purpose | Applies to |
| --- | --- | --- |
| [`discovery-catalog`](.github/skills/discovery-catalog/) | Read-only inventory of agents, starter-kits, and tools in this repo. Use for "list / describe / show" questions. | Catalog content (services-bound) |
| [`discovery-services-agent-deployer`](.github/skills/discovery-services-agent-deployer/) | Deploy one or more catalog agents to a Microsoft Foundry project. Handles tool build/push, agent deploy, resume, and validation. | Discovery services only |
| [`discovery-services-starter-kit-deployer`](.github/skills/discovery-services-starter-kit-deployer/) | Deploy a starter-kit by building/deploying its referenced tools, deploying each referenced agent, and printing customer-ready sample prompts. | Discovery services only |

### Verify the skills are loaded

In either Copilot CLI or VS Code Copilot Chat, after opening this repo:

```text
/skills
```

You should see all three skills listed. You can invoke them directly:

```text
/discovery-catalog agents
/discovery-services-agent-deployer <agent-name>
/discovery-services-starter-kit-deployer <starter-kit-name>
```

> **VS Code users:** when you first open this repo, VS Code will recommend the GitHub Copilot, Copilot Chat, PowerShell, Python, YAML, and markdownlint extensions (see [`.vscode/extensions.json`](.vscode/extensions.json)).

See each skill's `SKILL.md` for stage-by-stage runner details, configuration, and troubleshooting.

### Configure the deployer skills (one-time)

Before your first deploy, create local config files for the deployer skills:

- Copy `.github/skills/discovery-services-agent-deployer/config.template.json` → `config.json` (same folder).
- Copy `.github/skills/discovery-services-starter-kit-deployer/config.template.json` → `config.json` (same folder), or rely on the agent deployer config for shared Azure / Discovery settings.
- The starter-kit deployer config only uses these fields: `subscriptionId`, `resourceGroup`, `acrName`, `acrResourceGroup`, `location`, `apiVersion`, `workspaceEndpoint`, `project`, `tenantId`, `chatModel`, and `forceToolImageRebuild`.
- The agent deployer config additionally supports validation options such as `testPrompt`, `runReuseWindowMinutes`, `printAcrLogsOnFailure`, and `deleteInvestigationAfterTest`.
- `acrResourceGroup` is optional when ACR is in the same resource group as your Discovery resources.

> 🔒 **Keep `config.json` local.** Both files are gitignored and must not be committed — only the `config.template.json` files are tracked.

### Usage examples

Run these directly in Copilot Chat (CLI or VS Code):

**Inventory and discovery** ([`discovery-catalog`](.github/skills/discovery-catalog/))

```text
/discovery-catalog list agents
/discovery-catalog list starter-kits
/discovery-catalog describe chembl
/discovery-catalog list tools for agent aizynthfinder
```

**Deploy one or more agents** ([`discovery-services-agent-deployer`](.github/skills/discovery-services-agent-deployer/))

```text
/discovery-services-agent-deployer chembl
/discovery-services-agent-deployer chembl aizynthfinder
```

**Deploy a starter-kit** ([`discovery-services-starter-kit-deployer`](.github/skills/discovery-services-starter-kit-deployer/))

```text
/discovery-services-starter-kit-deployer drug-discovery
/discovery-services-starter-kit-deployer protein-structure-analysis
```

**Notes:**

- If prompted for a build mode, choose `remote` or `local` in chat.
- If referenced agents declare `discoveryExtensions.knowledgeBases`, provide the requested `knowledgeBaseId` values in `/bookshelves/{bookshelf}/knowledgeBases/{knowledgebase}/versions/{version}` format. Starter-kit deployment does not create knowledge bases; it patches user-provided IDs into each deployed agent.
- If prompted for Supercomputer nodepool confirmation, choose Proceed / Stop in chat before tool builds continue.
- Starter-kit deployment deploys each referenced agent individually and does not create a validation investigation; the summary lists deployed agents, deployed tools, and sample prompts you can use to test the deployment.

---

## 🤝 Contributing

All contributions — from Microsoft engineers and external partners — arrive via **pull request from a fork**. Direct pushes to `main` are not permitted.

| Type | Goes to | First read |
| --- | --- | --- |
| **New agent** | `agents/<agent-name>/` | [Agent authoring guide](docs/authoring-guides/agent-authoring-guide.md) |
| **New starter kit** | `starter-kits/<kit-name>/` | [Starter-kit authoring guide](docs/authoring-guides/starter-kit-authoring-guide.md) |
| **Documentation fix** | `docs/`, `README.md`, etc. | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| **Idea / feature request** | [Discussions → Ideas](https://github.com/microsoft/discovery/discussions/categories/ideas) | — |
| **Bug** | [Discussions → Bugs](https://github.com/microsoft/discovery/discussions/categories/bugs) | — |
| **Question** | [Discussions → Q&A](https://github.com/microsoft/discovery/discussions/categories/q-a) | — |
| **Something you built** | [Discussions → Show and tell](https://github.com/microsoft/discovery/discussions/categories/show-and-tell) | — |
| **Schema / workflow change** | PR against `docs/schemas/` or `.github/workflows/` — **Microsoft maintainers only**; open an Idea first. | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

The full contributor contract is in [`CONTRIBUTING.md`](CONTRIBUTING.md). Every PR runs through an automated review that validates structure, schemas, policy, documentation, and secrets — failures are reported inline with rule IDs and remediation hints.

### Quick start for catalog contributors

```bash
# Fork microsoft/discovery on GitHub, then:
git clone https://github.com/<your-alias>/discovery.git
cd discovery
git remote add upstream https://github.com/microsoft/discovery.git

# Create a branch and add your agent (or starter-kit) folder
git checkout -b add-my-agent
mkdir agents/my-agent
# … author metadata.yaml, agent.yaml, README.md (see authoring guide)

# Push and open a PR targeting upstream/main
git push origin add-my-agent
```

---

## 🆘 Getting help

Everything community-facing goes to **[Discussions](https://github.com/microsoft/discovery/discussions)**, posted in the matching category:

- **Questions / how-to** → [Q&A](https://github.com/microsoft/discovery/discussions/categories/q-a)
- **Bugs** → [Bugs](https://github.com/microsoft/discovery/discussions/categories/bugs) (the Bug template prompts you for version, repro steps, logs)
- **Ideas** → [Ideas](https://github.com/microsoft/discovery/discussions/categories/ideas)
- **Show what you've built** → [Show and tell](https://github.com/microsoft/discovery/discussions/categories/show-and-tell)

For security-sensitive reports, follow [`SECURITY.md`](SECURITY.md) — **do not** open a public Discussion or issue for vulnerabilities.

---

## ⚖️ Terms

This project follows the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). To report a security vulnerability, see [`SECURITY.md`](SECURITY.md).

**Trademarks** — this project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft trademarks or logos is subject to and must follow [Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/en-us/legal/intellectualproperty/trademarks/usage/general). Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship. Any use of third-party trademarks or logos is subject to those third parties' policies.

Third-party agent entries in the catalog are governed solely by each partner's own terms — see the individual agent `README.md` for details.
