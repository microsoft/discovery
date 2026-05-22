# Contributing

Thanks for your interest in contributing to **Microsoft Discovery**!

This repository serves **two purposes**:

1. **Discovery App distribution & community hub.** This repo is the home for the Microsoft Discovery app installer and product documentation. _Source code for Microsoft Discovery itself is not in this repository._
2. **Discovery Catalog.** This repo is the canonical metadata catalog for AI research **agents** (`agents/<name>/`) and **starter kits** (`starter-kits/<name>/`). Agent code, container images, and model weights live in your own infrastructure; the metadata and documentation that describe them live here.

The rest of this guide explains where each kind of contribution goes and what the PR-time checks expect. If you're new to Microsoft Discovery and want to install and try the app, start with the [end-user docs](docs/apps/) below.

---

## Using the Microsoft Discovery app

If you want to install and use the app, start here:

| Doc | What it covers |
| --- | --- |
| [`docs/apps/install.md`](docs/apps/install.md) | Prerequisites, download, install, verify, upgrade, uninstall, and a troubleshooting table. |
| [`docs/apps/quickstart.md`](docs/apps/quickstart.md) | 15-minute conceptual tour — Bookshelves, Tasks, Engines, Notebooks, and the `dx` CLI. |
| [`docs/apps/feedback.md`](docs/apps/feedback.md) | Where to file bugs, ideas, questions, and feature feedback. |

The remainder of this file is about **contributing** to the catalog (agents and starter kits) via pull request.

---

## Where contributions go

Code contributions to the Microsoft Discovery app itself — its plugin, MCP tool, and use-case surfaces — are not handled in this repository (the app's source code lives elsewhere). Conversations about those surfaces happen in **Discussions**. **Catalog metadata** (`agents/<name>/`, `starter-kits/<name>/`) and **documentation** are accepted via pull request. Every PR runs through an automated review that checks structure, schema conformance, documentation, and secrets; any failures are reported inline on the PR with a remediation hint.

| Type of contribution | Where it goes | Best for |
| --- | --- | --- |
| **Idea / feature request** | [Discussions → Ideas](https://github.com/microsoft/discovery/discussions/categories/ideas) | "It would be great if…", feedback on what could be better. |
| **Something you built** | [Discussions → Show and tell](https://github.com/microsoft/discovery/discussions/categories/show-and-tell) | Workflows, prompts, notebooks, or anything you've put together on top of Microsoft Discovery. |
| **Question** | [Discussions → Q&A](https://github.com/microsoft/discovery/discussions/categories/q-a) | "How do I…?", "Why does…?" |
| **Bug** | [Discussions → Bugs](https://github.com/microsoft/discovery/discussions/categories/bugs) | The Bug template prompts you for version, repro steps, logs, etc. |
| **Documentation fix** | Pull request against `docs/`, `README.md`, etc. | Typos, broken links, clarifications, missing prerequisites. |
| **New agent** | Pull request adding `agents/<agent-name>/` | A prompt agent + optional Discovery-managed tools. See the [Agent authoring guide](docs/authoring-guides/agent-authoring-guide.md). |
| **New starter kit** | Pull request adding `starter-kits/<starter-kit-name>/` | A `kit.json` manifest that bundles one or more agents into a launchable kit. See the [Starter-kit authoring guide](docs/authoring-guides/starter-kit-authoring-guide.md). |
| **Schema / workflow change** | Pull request against `docs/schemas/` or `.github/workflows/` — **Microsoft maintainers only**. External contributors should open an **Idea in Discussions** first; a Microsoft maintainer will land the change once it is agreed. | Schema and workflow edits are gated by branch protection and CODEOWNERS; fork PRs that modify these paths are auto-rejected. |
| **Discussion triage / answers** | [Discussions](https://github.com/microsoft/discovery/discussions) | Helping other community members. |

---

## Authoring a catalog PR

> Applies to agent submissions, starter-kit submissions, and documentation changes. Every PR runs through an automated review that enforces structural, schema, policy, documentation, and security checks. Address any failures reported on your PR; the comment includes a rule ID and a remediation hint. Detailed walkthroughs:
>
> - [Agent authoring guide](docs/authoring-guides/agent-authoring-guide.md)
> - [Starter-kit authoring guide](docs/authoring-guides/starter-kit-authoring-guide.md)

### Quick start

1. **Fork** this repo (external contributors) or create a topic branch (maintainers).
2. Add your agent under `agents/<agent-name>/` or your starter kit under `starter-kits/<starter-kit-name>/`. See [Repository layout](#repository-layout) below for the expected file tree.
3. Open a pull request against `main` and fill out **every** section of the PR template.
4. Automated checks will run on your PR. If anything fails, the bot adds an inline comment with the rule ID and how to fix it — address every finding before requesting human review.
5. When all checks pass, the `automated-checks-passed` label is applied and the [CODEOWNERS](.github/CODEOWNERS) maintainers are auto-requested for review. **Two approvals** are required to merge.

### Required files

#### For an agent (`agents/<agent-name>/`)

| File | Purpose | Schema |
|------|---------|--------|
| `metadata.yaml` | Identity, publisher info, tags, optional `publisher.party` (`1p` / `3p`) | [`docs/schemas/metadata-schema.json`](docs/schemas/metadata-schema.json) |
| `agent.yaml` | Prompt-agent definition (`kind: prompt` only) | [`docs/schemas/agent-schema-v2.json`](docs/schemas/agent-schema-v2.json) |
| `README.md` | Usage guide — must contain `## Overview`, `## Usage`, `## Prerequisites`, `## Architecture`, `## Configuration`, `## Known Limitations`, and `## Contributing` sections | n/a |
| `tools/<tool-name>/tool.yaml` (optional) | Discovery-managed tool definition | [`docs/schemas/tool-definition-schema.json`](docs/schemas/tool-definition-schema.json) |
| `tools/<tool-name>/Dockerfile` (optional) | Container build for the tool | n/a |

#### For a starter kit (`starter-kits/<starter-kit-name>/`)

The kit folder must contain **only** `kit.json`. Logos, screenshots, and any other assets must be referenced via HTTPS URLs — they cannot live inside the kit folder.

| File | Purpose | Schema |
|------|---------|--------|
| `kit.json` | Kit manifest — `agentRefs`, `defaultPrompts`, `samplePrompts`, optional `party` (`1p` / `3p`) | [`docs/schemas/starter-kit-schema.json`](docs/schemas/starter-kit-schema.json) |

### Authoring checklist

Before opening a PR, verify:

- [ ] Folder name matches `metadata.yaml.name` (or `kit.json.name`).
- [ ] `version` follows SemVer (`MAJOR.MINOR.PATCH`).
- [ ] `tags` are lowercase, hyphen-separated, and non-empty.
- [ ] `publisher.contact` is a valid email and `publisher.support_url` is HTTPS.
- [ ] `README.md` includes all required sections.
- [ ] No placeholder markers (`TODO`, `FIXME`, `XXX`) in metadata, agent definition, or README.
- [ ] No duplicate mapping keys in any YAML file.
- [ ] No hidden / OS artefacts (`.DS_Store`, `.env`, `*.swp`, `.idea/`, `.vs/`, etc.).
- [ ] No hand-edits to `.auto-registry/**` — the registries are rebuilt automatically after merge.
- [ ] If your agent depends on Discovery-managed tools, `agent.yaml.discoveryExtensions.tools[]` declares them.
- [ ] If model-weight files are added, they are Git-LFS tracked, ≤5 GB each, and in an allowed format.

### Schema changes

> **Microsoft maintainers only.** Edits under `docs/schemas/` define the contract every agent and kit in the repo must satisfy. Fork PRs that modify schema files are automatically rejected. If you are an external contributor and need a schema change, please [open an Idea in Discussions](https://github.com/microsoft/discovery/discussions/categories/ideas) describing the use case. A Microsoft maintainer will land the change once it is agreed.

---

## Repository layout

For the full repository layout — `agents/`, `starter-kits/`, `.auto-registry/`, `docs/`, `.github/`, and where each schema and script lives — see the **"Repository layout" section of [`README.md`](README.md)**.

Two things to remember as a contributor:

- Both `agents/` and `starter-kits/` use a **flat layout**: one folder per agent or kit directly under the parent directory — no `microsoft/` or `partners/` levels.
- A starter-kit folder may contain **only** `kit.json`. Logos, screenshots, READMEs, and other assets must be hosted externally and referenced by HTTPS URL (enforced by `SKT-STR-008` / `SKT-AST-001`).

---

## Contributor License Agreement

This project welcomes contributions and suggestions. Most contributions require you to agree to a Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us the rights to use your contribution. For details, visit <https://cla.opensource.microsoft.com>.

When you submit a pull request, a CLA bot will automatically determine whether you need to provide a CLA and decorate the PR appropriately (status check, comment, etc.). Simply follow the instructions provided by the bot. You will only need to do this once across all repos using our CLA.

## Code of Conduct

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/). For more information, see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or contact <opencode@microsoft.com> with any additional questions or comments.

## Reporting security issues

Please do **not** file public GitHub issues or Discussions for security reports. See [`SECURITY.md`](SECURITY.md) for the coordinated-disclosure process and contact address.
