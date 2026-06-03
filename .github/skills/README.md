# 🛠️ Copilot skills
> Scope: these skills target Microsoft Discovery services (the cloud-hosted experience on Microsoft Foundry). They are not used by, and have no effect on, the local Microsoft Discovery app today. If you're evaluating the app on your laptop, you can safely skip this section.
>

This repo ships three GitHub Copilot skills under .github/skills/. They are auto-discovered by both Copilot CLI and VS Code GitHub Copilot Chat — no /plugin install, no marketplace step, no per-machine setup. Just open the repo.

| Skill	| Purpose |	Applies to |
|-------|---------|------------|
| discovery-catalog	| Read-only inventory of agents, starter-kits, and tools in this repo. Use for "list / describe / show" questions. |	Catalog content (services-bound) |
| discovery-services-agent-deployer |	Deploy one or more catalog agents to a Microsoft Foundry project. Handles tool build/push, agent deploy, resume, and validation.	| Discovery services only |
| discovery-services-starter-kit-deployer	| Deploy a starter-kit by building/deploying its referenced tools, deploying each referenced agent, and printing customer-ready sample prompts.	| Discovery services only |

## Verify the skills are loaded
In either Copilot CLI or VS Code Copilot Chat, after opening this repo:

```
/skills
```

You should see all three skills listed. You can invoke them directly:

```
/discovery-catalog agents
/discovery-services-agent-deployer <agent-name>
/discovery-services-starter-kit-deployer <starter-kit-name>
```

> VS Code users: when you first open this repo, VS Code will recommend the GitHub Copilot, Copilot Chat, PowerShell, Python, YAML, and markdownlint extensions (see .vscode/extensions.json).
> 

See each skill's SKILL.md for stage-by-stage runner details, configuration, and troubleshooting.

## Configure the deployer skills (one-time)
Before your first deploy, create local config files for the deployer skills:

* Copy `.github/skills/discovery-services-agent-deployer/config.template.json` → `config.json` (same folder).
* Copy `.github/skills/discovery-services-starter-kit-deployer/config.template.json` → `config.json` (same folder), or rely on the agent deployer config for shared Azure / Discovery settings.
* The starter-kit deployer config only uses these fields: `subscriptionId`, `resourceGroup`, `acrName`, `acrResourceGroup`, `location`, `apiVersion`, `workspaceEndpoint`, `project`, `tenantId`, `chatModel`, and `forceToolImageRebuild`.
* The agent deployer config additionally supports validation options such as `testPrompt`, `runReuseWindowMinutes`, `printAcrLogsOnFailure`, and `deleteInvestigationAfterTest`.
* `acrResourceGroup` is optional when ACR is in the same resource group as your Discovery resources.

> 🔒 Keep config.json local. Both files are gitignored and must not be committed — only the config.template.json files are tracked.

## Usage examples
Run these directly in Copilot Chat (CLI or VS Code):

**Inventory and discovery ([discovery-catalog](https://github.com/microsoft/discovery/blob/main/.github/skills/discovery-catalog))**

```
/discovery-catalog list agents
/discovery-catalog list starter-kits
/discovery-catalog describe chembl
/discovery-catalog list tools for agent aizynthfinder
```

**Deploy one or more agents ([discovery-services-agent-deployer](https://github.com/microsoft/discovery/blob/main/.github/skills/discovery-services-agent-deployer))**

```
/discovery-services-agent-deployer chembl
/discovery-services-agent-deployer chembl aizynthfinder
```

**Deploy a starter-kit ([discovery-services-starter-kit-deployer](https://github.com/microsoft/discovery/blob/main/.github/skills/discovery-services-starter-kit-deployer))**

```
/discovery-services-starter-kit-deployer drug-discovery
/discovery-services-starter-kit-deployer protein-structure-analysis
```

**Notes:**

* If prompted for a build mode, choose remote or local in chat.
* If referenced agents declare discoveryExtensions.knowledgeBases, provide the requested knowledgeBaseId values in /bookshelves/{bookshelf}/knowledgeBases/{knowledgebase}/versions/{version} format. Starter-kit deployment does not create knowledge bases; it patches user-provided IDs into each deployed agent.
* If prompted for Supercomputer nodepool confirmation, choose Proceed / Stop in chat before tool builds continue.
* Starter-kit deployment deploys each referenced agent individually and does not create a validation investigation; the summary lists deployed agents, deployed tools, and sample prompts you can use to test the deployment.
